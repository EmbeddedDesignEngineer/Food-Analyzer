"""Validate local meal images before calling the AI layer."""

from __future__ import annotations

import errno
from pathlib import Path
import stat

from PIL import Image


class ImageValidationError(ValueError):
    """An image does not meet the application's input requirements."""


class ImageTooLargeError(ImageValidationError):
    """The image exceeds the caller's byte limit."""


class UnsupportedImageFormatError(ImageValidationError):
    """The detected format or filename suffix is unsupported."""


class InvalidImageError(ImageValidationError):
    """The image cannot be identified, verified, or decoded."""


_FORMAT_SUFFIXES = {"JPEG": {".jpg", ".jpeg"}, "PNG": {".png"}}


def validate_image(image_path: str | Path, *, max_size_bytes: int) -> Path:
    """Return an unchanged JPEG/PNG path after size and integrity checks.

    Validation failures raise ImageValidationError subclasses. Filesystem
    errors propagate unchanged. The caller supplies the size limit in bytes.
    """
    path = Path(image_path)
    if max_size_bytes <= 0:
        raise ValueError("max_size_bytes must be greater than zero")

    file_stat = path.stat()
    if stat.S_ISDIR(file_stat.st_mode):
        raise IsADirectoryError(errno.EISDIR, "Expected an image file", str(path))
    if not stat.S_ISREG(file_stat.st_mode):
        raise OSError(errno.EINVAL, "Expected a regular image file", str(path))
    if file_stat.st_size > max_size_bytes:
        raise ImageTooLargeError(
            f"Image {path} is {file_stat.st_size} bytes; maximum is {max_size_bytes} bytes"
        )

    try:
        with Image.open(path) as image:
            image_format = image.format
            if image_format not in _FORMAT_SUFFIXES:
                raise UnsupportedImageFormatError(
                    f"Image {path} has unsupported format {image_format!r}; use JPEG or PNG"
                )
            if path.suffix.lower() not in _FORMAT_SUFFIXES[image_format]:
                raise UnsupportedImageFormatError(
                    f"Image {path} has format {image_format} but incompatible suffix "
                    f"{path.suffix!r}"
                )
            image.verify()

        with Image.open(path) as image:
            image.load()
    except OSError as exc:
        # Pillow decoding errors usually have no errno; OS failures carry one.
        if exc.errno is not None or isinstance(exc, (PermissionError, FileNotFoundError)):
            raise
        raise InvalidImageError(f"Image {path} cannot be verified or decoded: {exc}") from exc
    except (SyntaxError, EOFError, Image.DecompressionBombError) as exc:
        raise InvalidImageError(f"Image {path} cannot be verified or decoded: {exc}") from exc

    return path
