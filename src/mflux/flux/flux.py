from pathlib import Path

import mlx.core as mx
from mlx import nn
from mlx.utils import tree_flatten
from tqdm import tqdm

from mflux.config.config import Config
from mflux.config.model_config import ModelConfig
from mflux.config.runtime_config import RuntimeConfig
from mflux.models.text_encoder.clip_encoder.clip_encoder import CLIPEncoder
from mflux.models.text_encoder.t5_encoder.t5_encoder import T5Encoder
from mflux.models.transformer.transformer import Transformer
from mflux.models.vae.vae import VAE
from mflux.post_processing.image import Image
from mflux.post_processing.image_util import ImageUtil
from mflux.tokenizer.clip_tokenizer import TokenizerCLIP
from mflux.tokenizer.t5_tokenizer import TokenizerT5
from mflux.tokenizer.tokenizer_handler import TokenizerHandler
from mflux.weights.weight_handler import WeightHandler


class Flux1:

    def __init__(
            self,
            model_config: ModelConfig,
            quantize: int | None = None,
            local_path: str | None = None,
            lora_paths: list[str] | None = None,
            lora_scales: list[float] | None = None,
    ):
        self.lora_paths = lora_paths
        self.lora_scales = lora_scales
        self.model_config = model_config

        # Load and initialize the tokenizers from disk, huggingface cache, or download from huggingface
        tokenizers = TokenizerHandler(model_config.model_name, self.model_config.max_sequence_length, local_path)
        self.t5_tokenizer = TokenizerT5(tokenizers.t5, max_length=self.model_config.max_sequence_length)
        self.clip_tokenizer = TokenizerCLIP(tokenizers.clip)

        # Initialize the models
        self.vae = VAE()
        self.transformer = Transformer(model_config)
        self.t5_text_encoder = T5Encoder()
        self.clip_text_encoder = CLIPEncoder()

        # Load the weights from disk, huggingface cache, or download from huggingface
        weights = WeightHandler(
            repo_id=model_config.model_name,
            local_path=local_path,
            lora_paths=lora_paths,
            lora_scales=lora_scales
        )

        # Set the loaded weights if they are not quantized
        if weights.quantization_level is None:
            self._set_model_weights(weights)

        # Optionally quantize the model here at initialization (also required if about to load quantized weights)
        self.bits = None
        if quantize is not None or weights.quantization_level is not None:
            self.bits = weights.quantization_level if weights.quantization_level is not None else quantize
            nn.quantize(self.vae, class_predicate=lambda _, m: isinstance(m, nn.Linear), group_size=64, bits=self.bits)
            nn.quantize(self.transformer, class_predicate=lambda _, m: isinstance(m, nn.Linear) and len(m.weight[1]) > 64, group_size=64, bits=self.bits)
            nn.quantize(self.t5_text_encoder, class_predicate=lambda _, m: isinstance(m, nn.Linear), group_size=64, bits=self.bits)
            nn.quantize(self.clip_text_encoder, class_predicate=lambda _, m: isinstance(m, nn.Linear), group_size=64, bits=self.bits)

        # If loading previously saved quantized weights, the weights must be set after modules have been quantized
        if weights.quantization_level is not None:
            self._set_model_weights(weights)

    def generate_image(self, seed: int, prompt: str, config: Config = Config()) -> Image:
        # Create a new runtime config based on the model type and input parameters
        config = RuntimeConfig(config, self.model_config)
        time_steps = tqdm(range(config.num_inference_steps))

        # 1. Create the initial latents
        latents = mx.random.normal(
            shape=[1, (config.height // 16) * (config.width // 16), 64],
            key=mx.random.key(seed)
        )

        # 2. Embedd the prompt
        t5_tokens = self.t5_tokenizer.tokenize(prompt)
        clip_tokens = self.clip_tokenizer.tokenize(prompt)
        prompt_embeds = self.t5_text_encoder.forward(t5_tokens)
        pooled_prompt_embeds = self.clip_text_encoder.forward(clip_tokens)

        for t in time_steps:
            # 3.t Predict the noise
            noise = self.transformer.predict(
                t=t,
                prompt_embeds=prompt_embeds,
                pooled_prompt_embeds=pooled_prompt_embeds,
                hidden_states=latents,
                config=config,
            )

            # 4.t Take one denoise step
            dt = config.sigmas[t + 1] - config.sigmas[t]
            latents += noise * dt

            # Evaluate to enable progress tracking
            mx.eval(latents)

        # 5. Decode the latent array and return the image
        latents = Flux1._unpack_latents(latents, config.height, config.width)
        decoded = self.vae.decode(latents)
        return ImageUtil.to_image(
            decoded_latents=decoded,
            seed=seed,
            prompt=prompt,
            quantization=self.bits,
            generation_time=time_steps.format_dict['elapsed'],
            lora_paths=self.lora_paths,
            lora_scales=self.lora_scales,
            config=config,
        )

    @staticmethod
    def _unpack_latents(latents: mx.array, height: int, width: int) -> mx.array:
        latents = mx.reshape(latents, (1, height // 16, width // 16, 16, 2, 2))
        latents = mx.transpose(latents, (0, 3, 1, 4, 2, 5))
        latents = mx.reshape(latents, (1, 16, height // 16 * 2, width // 16 * 2))
        return latents

    @staticmethod
    def from_alias(alias: str, quantize: int | None = None) -> "Flux1":
        return Flux1(
            model_config=ModelConfig.from_alias(alias),
            quantize=quantize,
        )

    def _set_model_weights(self, weights):
        self.vae.update(weights.vae)
        self.transformer.update(weights.transformer)
        self.t5_text_encoder.update(weights.t5_encoder)
        self.clip_text_encoder.update(weights.clip_encoder)

    def save_model(self, base_path: str):
        def _save_tokenizer(tokenizer, subdir: str):
            path = Path(base_path) / subdir
            path.mkdir(parents=True, exist_ok=True)
            tokenizer.save_pretrained(path)

        def _save_weights(model, subdir: str):
            path = Path(base_path) / subdir
            path.mkdir(parents=True, exist_ok=True)
            weights = _split_weights(dict(tree_flatten(model.parameters())))
            for i, weight in enumerate(weights):
                mx.save_safetensors(str(path / f"{i}.safetensors"), weight, {"quantization_level": str(self.bits)})

        def _split_weights(weights: dict, max_file_size_gb: int = 2) -> list:
            # Copied from mlx-examples repo
            max_file_size_bytes = max_file_size_gb << 30
            shards = []
            shard, shard_size = {}, 0
            for k, v in weights.items():
                if shard_size + v.nbytes > max_file_size_bytes:
                    shards.append(shard)
                    shard, shard_size = {}, 0
                shard[k] = v
                shard_size += v.nbytes
            shards.append(shard)
            return shards

        # Save the tokenizers
        _save_tokenizer(self.clip_tokenizer.tokenizer, "tokenizer")
        _save_tokenizer(self.t5_tokenizer.tokenizer, "tokenizer_2")

        # Save the models
        _save_weights(self.vae, "vae")
        _save_weights(self.transformer, "transformer")
        _save_weights(self.clip_text_encoder, "text_encoder")
        _save_weights(self.t5_text_encoder, "text_encoder_2")