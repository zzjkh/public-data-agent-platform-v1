from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile


SUPPORTED_FILE_TYPES = {
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".csv": "csv",
    ".xlsx": "xlsx",
}


@dataclass(frozen=True)
class StoredFile:
    file_name: str
    file_type: str
    storage_uri: str
    file_hash: str
    size_bytes: int


class UnsupportedFileTypeError(ValueError):
    pass


class EmptyUploadError(ValueError):
    pass


def infer_file_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    file_type = SUPPORTED_FILE_TYPES.get(suffix)
    if file_type is None:
        supported = ", ".join(sorted(SUPPORTED_FILE_TYPES))
        raise UnsupportedFileTypeError(f"Unsupported file type: {suffix or '<none>'}. Supported: {supported}")
    return file_type


class LocalFileStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save_upload(self, upload_file: UploadFile) -> StoredFile:
        file_name = Path(upload_file.filename or "uploaded_file").name
        file_type = infer_file_type(file_name)
        suffix = Path(file_name).suffix.lower()

        tmp_dir = self.root / "_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"{uuid4().hex}.upload"

        file_hash = hashlib.sha256()
        size_bytes = 0
        try:
            with tmp_path.open("wb") as destination:
                while chunk := upload_file.file.read(1024 * 1024):
                    size_bytes += len(chunk)
                    file_hash.update(chunk)
                    destination.write(chunk)

            if size_bytes == 0:
                raise EmptyUploadError("Uploaded file is empty")

            digest = file_hash.hexdigest()
            relative_path = Path("source_files") / digest[:2] / f"{digest}{suffix}"
            final_path = self.root / relative_path
            final_path.parent.mkdir(parents=True, exist_ok=True)

            if final_path.exists():
                tmp_path.unlink(missing_ok=True)
            else:
                tmp_path.replace(final_path)

            return StoredFile(
                file_name=file_name,
                file_type=file_type,
                storage_uri=f"local://{relative_path.as_posix()}",
                file_hash=digest,
                size_bytes=size_bytes,
            )
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def resolve(self, storage_uri: str) -> Path:
        prefix = "local://"
        if not storage_uri.startswith(prefix):
            raise ValueError(f"Unsupported storage URI: {storage_uri}")
        relative = storage_uri[len(prefix) :]
        path = (self.root / relative).resolve()
        root = self.root.resolve()
        if not path.is_relative_to(root):
            raise ValueError("Storage URI resolves outside file storage root")
        return path
