from __future__ import annotations

import math
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from app import config
from app.main import app


client = TestClient(app)


def make_wav(path: Path, seconds: float = 0.25, rate: int = 8000) -> None:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        for index in range(frames):
            sample = int(12000 * math.sin(2 * math.pi * 440 * index / rate))
            wav.writeframesraw(sample.to_bytes(2, "little", signed=True))


def test_valid_wav_upload_returns_transcript(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    wav_path = tmp_path / "valid.wav"
    make_wav(wav_path)

    with wav_path.open("rb") as file:
        response = client.post("/api/uploads", files={"file": ("valid.wav", file, "audio/wav")})

    assert response.status_code == 200
    payload = response.json()
    assert payload["audioUrl"].startswith("/api/uploads/")
    assert payload["transcript"]["notes"][0]["hand"] == "unknown"
    assert (tmp_path / "uploads" / f"{payload['uploadId']}.wav").exists()


def test_rejects_extension_with_valid_content(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    wav_path = tmp_path / "valid.wav"
    make_wav(wav_path)

    with wav_path.open("rb") as file:
        response = client.post("/api/uploads", files={"file": ("../bad.txt", file, "text/plain")})

    assert response.status_code == 400
    assert "wav" in response.json()["detail"].lower()


def test_rejects_fake_wav(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    fake_path = tmp_path / "fake.wav"
    fake_path.write_bytes(b"not a real wav")

    with fake_path.open("rb") as file:
        response = client.post("/api/uploads", files={"file": ("fake.wav", file, "audio/wav")})

    assert response.status_code == 400
    assert "valid wav or mp3" in response.json()["detail"].lower()


def test_rejects_oversized_upload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 4)
    wav_path = tmp_path / "valid.wav"
    make_wav(wav_path)

    with wav_path.open("rb") as file:
        response = client.post("/api/uploads", files={"file": ("valid.wav", file, "audio/wav")})

    assert response.status_code == 413


def test_rejects_audio_over_duration_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1024 * 1024)
    monkeypatch.setattr(config, "MAX_AUDIO_SECONDS", 0.1)
    wav_path = tmp_path / "long.wav"
    make_wav(wav_path, seconds=0.25)

    with wav_path.open("rb") as file:
        response = client.post("/api/uploads", files={"file": ("long.wav", file, "audio/wav")})

    assert response.status_code == 400
    assert "duration" in response.json()["detail"].lower()

