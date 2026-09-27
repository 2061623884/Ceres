"""Raster product image helpers."""

from __future__ import annotations

from pathlib import Path

RASTER_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

# Core SKUs that must have recognizable raster photos (not color-block placeholders).
CORE_SKU_PATTERNS = ("tomato", "green_pepper", "pork_loin", "egg", "peanut")

# Core demo product images — must be real photos, never generated packaging blocks.
CORE_DEMO_IMAGE_FILES = frozenset(
    {
        "demo-tomato-fresh-500g.jpg",
        "demo-bell-pepper-300g.jpg",
        "demo-pork-500g.jpg",
        "demo-eggs-fresh-6pack.jpg",
        "demo-peanut-200g.jpg",
    }
)

def _basename(image_path: str) -> str:
    return Path(image_path.replace("\\", "/")).name.lower()


def is_raster_image_path(image_path: str | None, root: Path | None = None) -> bool:
    """True when path points to an on-disk raster product photo."""
    if not image_path:
        return False
    lower = image_path.lower()
    if not any(lower.endswith(suffix) for suffix in RASTER_SUFFIXES):
        return False
    if root is None:
        return True
    rel = image_path.replace("\\", "/").lstrip("/")
    file_path = root / rel
    return file_path.is_file()


def image_kind_for_path(image_path: str | None, root: Path | None = None) -> str:
    """Classify image asset kind. Does not mechanically map legacy demo_photo to photo."""
    if is_raster_image_path(image_path, root):
        return "photo"
    if image_path and image_path.lower().endswith(".svg"):
        return "placeholder"
    if image_path:
        return "unverified"
    return "placeholder"


def image_kind_legacy(image_kind: str) -> str:
    """Backward-compatible read mapping for old clients."""
    if image_kind == "photo":
        return "demo_photo"
    if image_kind in ("placeholder", "packaging_illustration"):
        return "placeholder"
    return "missing"


def is_core_demo_photo(image_path: str | None, root: Path | None = None) -> bool:
    """True when a core SKU demo image exists on disk and is classified as photo."""
    if not image_path or _basename(image_path) not in CORE_DEMO_IMAGE_FILES:
        return False
    return image_kind_for_path(image_path, root) == "photo"
