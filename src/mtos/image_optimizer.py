"""Shared image normalization used by uploads and directory imports."""

import tempfile
from pathlib import Path

from PIL import Image, ImageOps

MAX_IMAGE_SIZE = (1280, 720)
ASPECT_RATIO = (16, 9)
JPEG_QUALITY = 85


def optimize_image(source: Path, destination: Path) -> None:
    """Atomically create a center-cropped 16:9 JPEG, at most 1280x720."""
    temporary_name = None
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                image = Image.new("RGB", rgba.size, "white")
                image.paste(rgba, mask=rgba.getchannel("A"))
            elif image.mode != "RGB":
                image = image.convert("RGB")
            if image.width < ASPECT_RATIO[0] or image.height < ASPECT_RATIO[1]:
                raise ValueError("image must be at least 16 by 9 pixels")
            scale = min(
                MAX_IMAGE_SIZE[0] // ASPECT_RATIO[0],
                MAX_IMAGE_SIZE[1] // ASPECT_RATIO[1],
                image.width // ASPECT_RATIO[0],
                image.height // ASPECT_RATIO[1],
            )
            output_size = (
                ASPECT_RATIO[0] * scale,
                ASPECT_RATIO[1] * scale,
            )
            image = ImageOps.fit(
                image,
                output_size,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.stem}_",
                suffix=".jpg",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
            image.save(
                temporary_name,
                format="JPEG",
                quality=JPEG_QUALITY,
                optimize=True,
                progressive=True,
            )
        Path(temporary_name).replace(destination)
    except Exception:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        raise
