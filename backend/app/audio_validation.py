from __future__ import annotations

import re
import shutil
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import HTTPException, UploadFile
from mutagen.mp3 import HeaderNotFoundError, MP3

from . import config


ALLOWED_EXTENSIONS = {".wav", ".mp3"}
SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class StoredAudio:
    upload_id: str
    original_filename: str
    stored_filename: str
    media_type: str
    duration: float
    size: int


def sanitize_filename(filename: str | None) -> str:
    name = Path(filename or "upload").name
    name = SAFE_NAME_PATTERN.sub("_", name).strip("._")
    return name or "upload"


def ensure_child_path(parent: Path, child: Path) -> Path:
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    if parent_resolved not in child_resolved.parents and child_resolved != parent_resolved:
        raise HTTPException(status_code=400, detail="Invalid upload path")
    return child_resolved


def sniff_audio_type(path: Path, extension: str) -> str:
    with path.open("rb") as file:
        header = file.read(12)
    if extension == ".wav" and header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return "audio/wav"
    if extension == ".mp3" and (header.startswith(b"ID3") or header[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}):
        return "audio/mpeg"
    raise HTTPException(status_code=400, detail="Only valid WAV or MP3 files are allowed")


def audio_duration_seconds(path: Path, extension: str) -> float:
    if extension == ".wav":
        try:
            with wave.open(str(path), "rb") as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                if rate <= 0:
                    raise HTTPException(status_code=400, detail="Invalid WAV sample rate")
                return frames / float(rate)
        except wave.Error as exc:
            raise HTTPException(status_code=400, detail="Invalid WAV file") from exc

    if extension == ".mp3":
        try:
            return float(MP3(path).info.length)
        except (HeaderNotFoundError, AttributeError, OSError) as exc:
            raise HTTPException(status_code=400, detail="Invalid MP3 file") from exc

    raise HTTPException(status_code=400, detail="Unsupported audio type")


async def store_validated_audio(file: UploadFile) -> StoredAudio:
    original_filename = sanitize_filename(file.filename)
    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only .wav and .mp3 uploads are allowed")

    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    size = 0
    with NamedTemporaryFile(delete=False, suffix=extension, dir=config.UPLOAD_DIR) as tmp:
        temp_path = Path(tmp.name)
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > config.MAX_UPLOAD_BYTES:
                temp_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Upload exceeds configured max size")
            tmp.write(chunk)

    if size == 0:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    media_type = sniff_audio_type(temp_path, extension)
    duration = audio_duration_seconds(temp_path, extension)
    if duration > config.MAX_AUDIO_SECONDS:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Audio duration exceeds configured limit")

    upload_id = uuid.uuid4().hex
    stored_filename = f"{upload_id}{extension}"
    destination = ensure_child_path(config.UPLOAD_DIR, config.UPLOAD_DIR / stored_filename)
    shutil.move(str(temp_path), destination)

    return StoredAudio(
        upload_id=upload_id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        media_type=media_type,
        duration=duration,
        size=size,
    )

