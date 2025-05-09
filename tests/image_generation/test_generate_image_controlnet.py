from mflux import ModelConfig
from tests.image_generation.helpers.image_generation_controlnet_test_helper import ImageGeneratorControlnetTestHelper


class TestImageGeneratorControlnet:
    CONTROLNET_REFERENCE_FILENAME = "controlnet_reference.png"

    def test_image_generation_schnell_controlnet(self):
        ImageGeneratorControlnetTestHelper.assert_matches_reference_image(
            reference_image_path="reference_controlnet_schnell.png",
            output_image_path="output_controlnet_schnell.png",
            controlnet_image_path=TestImageGeneratorControlnet.CONTROLNET_REFERENCE_FILENAME,
            model_config=ModelConfig.schnell(),
            steps=2,
            seed=43,
            prompt="The joker with a hat and a cane",
            controlnet_strength=0.4,
        )

    def test_image_generation_dev_controlnet(self):
        ImageGeneratorControlnetTestHelper.assert_matches_reference_image(
            reference_image_path="reference_controlnet_dev.png",
            output_image_path="output_controlnet_dev.png",
            controlnet_image_path=TestImageGeneratorControlnet.CONTROLNET_REFERENCE_FILENAME,
            model_config=ModelConfig.dev(),
            steps=15,
            seed=42,
            prompt="The joker with a hat and a cane",
            controlnet_strength=0.4,
        )

    def test_image_generation_dev_lora_controlnet(self):
        ImageGeneratorControlnetTestHelper.assert_matches_reference_image(
            reference_image_path="reference_controlnet_dev_lora.png",
            output_image_path="output_controlnet_dev_lora.png",
            controlnet_image_path=TestImageGeneratorControlnet.CONTROLNET_REFERENCE_FILENAME,
            model_config=ModelConfig.dev(),
            steps=15,
            seed=43,
            prompt="mkym this is made of wool, The joker with a hat and a cane",
            lora_paths=["FLUX-dev-lora-MiaoKa-Yarn-World.safetensors"],
            lora_scales=[1.0],
            controlnet_strength=0.4,
        )
