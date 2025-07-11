import json
import logging
from pathlib import Path

import mlx.core as mx
import numpy as np
import piexif
import PIL.Image
import PIL.ImageDraw
from PIL._typing import StrOrBytesPath

from mflux.community.concept_attention.attention_data import ConceptHeatmap
from mflux.config.runtime_config import RuntimeConfig
from mflux.post_processing.generated_image import GeneratedImage
from mflux.ui.box_values import AbsoluteBoxValues, BoxValues

log = logging.getLogger(__name__)


class ImageUtil:
    @staticmethod
    def to_image(
        decoded_latents: mx.array,
        config: RuntimeConfig,
        seed: int,
        prompt: str,
        quantization: int,
        generation_time: float,
        lora_paths: list[str],
        lora_scales: list[float],
        controlnet_image_path: str | Path | None = None,
        image_path: str | Path | None = None,
        redux_image_paths: list[str] | list[Path] | None = None,
        redux_image_strengths: list[float] | None = None,
        image_strength: float | None = None,
        masked_image_path: str | Path | None = None,
        depth_image_path: str | Path | None = None,
        concept_heatmap: ConceptHeatmap | None = None,
    ) -> GeneratedImage:
        normalized = ImageUtil._denormalize(decoded_latents)
        normalized_numpy = ImageUtil._to_numpy(normalized)
        image = ImageUtil._numpy_to_pil(normalized_numpy)
        return GeneratedImage(
            image=image,
            model_config=config.model_config,
            seed=seed,
            steps=config.num_inference_steps,
            prompt=prompt,
            guidance=config.guidance,
            precision=config.precision,
            quantization=quantization,
            generation_time=generation_time,
            lora_paths=lora_paths,
            lora_scales=lora_scales,
            image_path=image_path,
            image_strength=image_strength,
            controlnet_image_path=controlnet_image_path,
            controlnet_strength=config.controlnet_strength,
            masked_image_path=masked_image_path,
            depth_image_path=depth_image_path,
            redux_image_paths=redux_image_paths,
            redux_image_strengths=redux_image_strengths,
            concept_heatmap=concept_heatmap,
        )

    @staticmethod
    def to_composite_image(generated_images: list[GeneratedImage]) -> PIL.Image.Image:
        # stitch horizontally
        total_width = sum(gen_img.image.width for gen_img in generated_images)
        max_height = max(gen_img.image.height for gen_img in generated_images)
        composite_img = PIL.Image.new("RGB", (total_width, max_height))
        current_x = 0
        for index, gen_img in enumerate(generated_images):
            composite_img.paste(gen_img.image, (current_x, 0))
            current_x += gen_img.image.width
        return composite_img

    @staticmethod
    def _denormalize(images: mx.array) -> mx.array:
        return mx.clip((images / 2 + 0.5), 0, 1)

    @staticmethod
    def _normalize(images: mx.array) -> mx.array:
        return 2.0 * images - 1.0

    @staticmethod
    def _binarize(image: mx.array) -> mx.array:
        return mx.where(image < 0.5, mx.zeros_like(image), mx.ones_like(image))

    @staticmethod
    def _to_numpy(images: mx.array) -> np.ndarray:
        images = mx.transpose(images, (0, 2, 3, 1))
        images = mx.array.astype(images, mx.float32)
        images = np.array(images)
        return images

    @staticmethod
    def _numpy_to_pil(images: np.ndarray) -> PIL.Image.Image:
        images = (images * 255).round().astype("uint8")
        pil_images = [PIL.Image.fromarray(image) for image in images]
        return pil_images[0]

    @staticmethod
    def _pil_to_numpy(image: PIL.Image.Image) -> np.ndarray:
        image = np.array(image).astype(np.float32) / 255.0
        images = np.stack([image], axis=0)
        return images

    @staticmethod
    def to_array(image: PIL.Image.Image, is_mask: bool = False) -> mx.array:
        image = ImageUtil._pil_to_numpy(image)
        array = mx.array(image)
        array = mx.transpose(array, (0, 3, 1, 2))
        if is_mask:
            array = ImageUtil._binarize(array)
        else:
            array = ImageUtil._normalize(array)
        return array

    @staticmethod
    def load_image(image_or_path: PIL.Image.Image | StrOrBytesPath) -> PIL.Image.Image:
        if isinstance(image_or_path, PIL.Image.Image):
            return image_or_path.convert("RGB")
        else:
            return PIL.Image.open(image_or_path).convert("RGB")

    @staticmethod
    def expand_image(
        image: PIL.Image.Image,
        box_values: AbsoluteBoxValues | None = None,
        top: int | str = 0,
        right: int | str = 0,
        bottom: int | str = 0,
        left: int | str = 0,
        fill_color: tuple = (255, 255, 255),
    ) -> PIL.Image.Image:
        """
        Expand the image by padding it with the top/right/bottom/left box values specified
        in either pixels or percentages relative to original image dimensions.
        """
        if box_values is None:
            box_values = BoxValues(top=top, right=right, bottom=bottom, left=left).normalize_to_dimensions(
                image.width, image.height
            )  # Create new image with expanded dimensions, paste the original image into it

        new_width = image.width + box_values.left + box_values.right
        new_height = image.height + box_values.top + box_values.bottom
        expanded_image = PIL.Image.new(image.mode, (new_width, new_height), fill_color)
        expanded_image.paste(image, (box_values.left, box_values.top))
        return expanded_image

    @staticmethod
    def create_outpaint_mask_image(orig_width: int, orig_height: int, **create_bordered_image_kwargs):
        """
        Create an outpaint mask image that is black in the middle representing the original image dimensions
        and a white border on the outside paddings representing the areas to be painted over.
        """
        return ImageUtil.create_bordered_image(
            orig_width,
            orig_height,
            border_color=(255, 255, 255),
            content_color=(0, 0, 0),
            **create_bordered_image_kwargs,
        )

    @staticmethod
    def create_bordered_image(
        orig_width: int,
        orig_height: int,
        border_color: tuple,
        content_color: tuple,
        box_values: AbsoluteBoxValues | None = None,
        top: int | str = 0,
        right: int | str = 0,
        bottom: int | str = 0,
        left: int | str = 0,
    ) -> PIL.Image.Image:
        """
        Create an image with border color and a content/fill-colored center based on CSS box model values.
        """
        if box_values is None:
            box_values = BoxValues(top=top, right=right, bottom=bottom, left=left).normalize_to_dimensions(
                orig_width, orig_height
            )

        # Create a new white image
        new_width = orig_width + box_values.right + box_values.left
        new_height = orig_height + box_values.top + box_values.bottom

        result = PIL.Image.new("RGB", (new_width, new_height), border_color)
        draw = PIL.ImageDraw.Draw(result)

        # Draw black rectangle in the center
        draw.rectangle(
            [(box_values.left, box_values.top), (box_values.left + orig_width, box_values.top + orig_height)],
            fill=content_color,
        )

        return result

    @staticmethod
    def scale_to_dimensions(
        image: PIL.Image.Image,
        target_width: int,
        target_height: int,
    ) -> PIL.Image.Image:
        if (image.width, image.height) != (target_width, target_height):
            return image.resize((target_width, target_height), PIL.Image.LANCZOS)
        else:
            return image

    @staticmethod
    def save_image(
        image: PIL.Image.Image,
        path: str | Path,
        metadata: dict | None = None,
        export_json_metadata: bool = False,
        overwrite: bool = False,
    ) -> None:
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_name = file_path.stem
        file_extension = file_path.suffix

        # If a file already exists and overwrite is False, create a new name with a counter
        if not overwrite:
            counter = 1
            while file_path.exists():
                new_name = f"{file_name}_{counter}{file_extension}"
                file_path = file_path.with_name(new_name)
                counter += 1

        try:
            # Save image without metadata first
            image.save(file_path)
            log.info(f"Image saved successfully at: {file_path}")

            # Optionally save json metadata file
            if export_json_metadata:
                with open(f"{file_path.with_suffix('.json')}", "w") as json_file:
                    json.dump(metadata, json_file, indent=4)

            # Embed metadata
            if metadata is not None:
                ImageUtil._embed_metadata(metadata, file_path)
                log.info(f"Metadata embedded successfully at: {file_path}")
        except Exception as e:  # noqa: BLE001
            log.error(f"Error saving image: {e}")

    @staticmethod
    def _embed_metadata(metadata: dict, path: str | Path) -> None:
        try:
            # Convert metadata dictionary to a string
            metadata_str = json.dumps(metadata)

            # Convert the string to bytes (using UTF-8 encoding)
            user_comment_bytes = metadata_str.encode("utf-8")

            # Define the UserComment tag ID
            USER_COMMENT_TAG_ID = 0x9286

            # Create a piexif-compatible dictionary structure
            exif_piexif_dict = {"Exif": {USER_COMMENT_TAG_ID: user_comment_bytes}}

            # Load the image and embed the EXIF data
            image = PIL.Image.open(path)
            exif_bytes = piexif.dump(exif_piexif_dict)
            image.info["exif"] = exif_bytes

            # Save the image with metadata
            image.save(path, exif=exif_bytes)

        except Exception as e:  # noqa: BLE001
            log.error(f"Error embedding metadata: {e}")

    @staticmethod
    def preprocess_for_model(
        image: PIL.Image.Image,
        target_size: tuple = (384, 384),
        mean: list = [0.5, 0.5, 0.5],
        std: list = [0.5, 0.5, 0.5],
        resample: int = PIL.Image.LANCZOS,
    ) -> mx.array:
        # Resize the image to target size
        image = image.resize(target_size, resample=resample)

        # Convert PIL image to numpy array and normalize to [0, 1]
        image_np = np.array(image).astype(np.float32) / 255.0

        # Normalize using specified mean and std
        mean_np = np.array(mean)
        std_np = np.array(std)
        image_np = (image_np - mean_np) / std_np

        # Convert from HWC to CHW format
        image_np = image_np.transpose(2, 0, 1)

        # Convert to MLX array and add batch dimension
        image_mx = mx.array(image_np)
        image_mx = mx.expand_dims(image_mx, axis=0)

        return image_mx

    @staticmethod
    def preprocess_for_depth_pro(
        image: PIL.Image.Image,
        target_size: tuple = (384, 384),
        mean: list = [0.5, 0.5, 0.5],
        std: list = [0.5, 0.5, 0.5],
        resample: int = PIL.Image.LANCZOS,
    ) -> mx.array:
        # Convert PIL image to numpy array and normalize to [0, 1]
        image_np = np.array(image).astype(np.float32) / 255.0

        # Convert from HWC to CHW format
        image_np = image_np.transpose(2, 0, 1)

        # Normalize using specified mean and std
        mean_np = np.array(mean).reshape(-1, 1, 1)
        std_np = np.array(std).reshape(-1, 1, 1)
        image_np = (image_np - mean_np) / std_np

        # Convert to MLX array
        return mx.array(image_np)
