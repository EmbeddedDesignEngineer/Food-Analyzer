"""Offline image validation tests using generated images and local files."""

from __future__ import annotations

import errno
import os
from pathlib import Path

from PIL import Image, PngImagePlugin
import pytest

from src.services.image_validation import (
    ImageTooLargeError,
    ImageValidationError,
    InvalidImageError,
    UnsupportedImageFormatError,
    validate_image,
)


def make_image(path: Path, image_format: str = "PNG") -> Path:
    with Image.new("RGB", (16, 16), color="green") as image:
        image.save(path, format=image_format)
    return path


@pytest.mark.parametrize(
    ("image_format", "suffix"),
    [("PNG", ".png"), ("JPEG", ".jpg"), ("JPEG", ".jpeg"),
     ("PNG", ".PNG"), ("JPEG", ".JPG"), ("JPEG", ".JPEG")],
)
@pytest.mark.parametrize("as_string", [False, True])
def test_valid_images(tmp_path, image_format, suffix, as_string):
    path = make_image(tmp_path / f"meal{suffix}", image_format)
    before = path.read_bytes()
    result = validate_image(
        str(path) if as_string else path, max_size_bytes=len(before)
    )
    assert isinstance(result, Path)
    assert result == path
    assert path.read_bytes() == before


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_image(tmp_path / "missing.png", max_size_bytes=1000)


def test_directory(tmp_path):
    with pytest.raises(IsADirectoryError):
        validate_image(tmp_path, max_size_bytes=1000)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Requires named pipe support")
def test_nonregular_file(tmp_path):
    path = tmp_path / "pipe.png"
    os.mkfifo(path)
    with pytest.raises(OSError) as caught:
        validate_image(path, max_size_bytes=1000)
    assert caught.value.errno == errno.EINVAL


@pytest.mark.parametrize("limit", [0, -1])
def test_nonpositive_limit(tmp_path, limit):
    path = make_image(tmp_path / "meal.png")
    with pytest.raises(ValueError, match="max_size_bytes"):
        validate_image(path, max_size_bytes=limit)


def test_oversize_rejected_before_pillow(tmp_path, monkeypatch):
    path = make_image(tmp_path / "meal.png")

    def unexpected_open(*args, **kwargs):
        pytest.fail("Oversized files must be rejected before Pillow opens them")

    monkeypatch.setattr(Image, "open", unexpected_open)
    with pytest.raises(ImageTooLargeError, match="maximum"):
        validate_image(path, max_size_bytes=path.stat().st_size - 1)


@pytest.mark.parametrize(
    ("image_format", "suffix"),
    [("GIF", ".gif"), ("BMP", ".bmp"), ("GIF", ".png"),
     ("BMP", ".jpg"), ("PNG", ".jpg"), ("JPEG", ".png"),
     ("PNG", ".txt"), ("JPEG", "")],
)
def test_unsupported_format_or_suffix(tmp_path, image_format, suffix):
    path = make_image(tmp_path / f"meal{suffix}", image_format)
    with pytest.raises(UnsupportedImageFormatError):
        validate_image(path, max_size_bytes=path.stat().st_size)


@pytest.mark.parametrize("content", [b"", b"This is not an image"])
def test_invalid_contents(tmp_path, content):
    path = tmp_path / "meal.png"
    path.write_bytes(content)
    with pytest.raises(InvalidImageError) as caught:
        validate_image(path, max_size_bytes=1000)
    assert caught.value.__cause__ is not None


@pytest.mark.parametrize("image_format,suffix", [("PNG", ".png"), ("JPEG", ".jpg")])
def test_truncated_image(tmp_path, image_format, suffix):
    path = make_image(tmp_path / f"meal{suffix}", image_format)
    path.write_bytes(path.read_bytes()[:-12])
    with pytest.raises(InvalidImageError) as caught:
        validate_image(path, max_size_bytes=1000)
    assert caught.value.__cause__ is not None


def test_decode_failure_after_verification(tmp_path, monkeypatch):
    path = make_image(tmp_path / "meal.png")
    failure = OSError("broken pixel data")

    def fail_load(self, *args, **kwargs):
        raise failure

    monkeypatch.setattr(PngImagePlugin.PngImageFile, "load", fail_load)
    with pytest.raises(InvalidImageError) as caught:
        validate_image(path, max_size_bytes=1000)
    assert caught.value.__cause__ is failure


@pytest.mark.parametrize("stage", ["stat", "open", "load"])
@pytest.mark.parametrize("error_type,code", [(PermissionError, errno.EACCES), (OSError, errno.EIO)])
def test_filesystem_errors_preserved(tmp_path, monkeypatch, stage, error_type, code):
    path = make_image(tmp_path / "meal.png")
    failure = error_type(code, "Filesystem failure", str(path))

    def fail(*args, **kwargs):
        raise failure

    with monkeypatch.context() as patch:
        if stage == "stat":
            patch.setattr(Path, "stat", fail)
        elif stage == "open":
            patch.setattr(Image, "open", fail)
        else:
            patch.setattr(PngImagePlugin.PngImageFile, "load", fail)
        with pytest.raises(error_type) as caught:
            validate_image(path, max_size_bytes=1000)
    assert caught.value is failure


@pytest.mark.parametrize(
    "error_type", [ImageTooLargeError, UnsupportedImageFormatError, InvalidImageError]
)
def test_validation_exception_hierarchy(error_type):
    assert issubclass(error_type, ImageValidationError)
    assert issubclass(ImageValidationError, ValueError)
