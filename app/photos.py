"""Storing photos.

Like the mailer, photos go through a small interface: locally they're
saved in uploads/, and in production (Phase 7) they'll go to AWS S3.
"""

from pathlib import Path
from typing import Protocol

from app.config import settings


class PhotoStore(Protocol):
    def save(self, key: str, data: bytes) -> None: ...
    def load(self, key: str) -> bytes: ...


class LocalPhotoStore:
    def __init__(self, root: str = "uploads"):
        self.root = Path(root)

    def save(self, key: str, data: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def load(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


store: PhotoStore | None = None  # created on first use; tests swap in a temp folder


def get_store() -> PhotoStore:
    global store
    if store is None:
        if settings.photo_store != "local":
            raise NotImplementedError(f"PHOTO_STORE={settings.photo_store!r} is not available yet (S3 comes in Phase 7)")
        store = LocalPhotoStore()
    return store


def detect_image_type(data: bytes) -> tuple[str, str] | None:
    """Look at the file's first bytes (not its name) to see what it really is.

    Returns (content type, file extension), or None if it isn't a JPEG or PNG.
    HEIC (iPhone) support needs an extra library and is left for later.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    return None


def make_key(issue_id: str, sha256: str, ext: str) -> str:
    """Name files by their fingerprint, so the same photo is never stored twice."""
    return f"{issue_id}/{sha256}.{ext}"
