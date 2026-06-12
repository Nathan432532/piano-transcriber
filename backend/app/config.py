from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("PIANO_TRANSCRIBER_DATA_DIR", BASE_DIR / "data")).resolve()
UPLOAD_DIR = (DATA_DIR / "uploads").resolve()
SAMPLE_DIR = (DATA_DIR / "samples").resolve()
MAX_UPLOAD_BYTES = int(os.getenv("PIANO_TRANSCRIBER_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
MAX_AUDIO_SECONDS = float(os.getenv("PIANO_TRANSCRIBER_MAX_AUDIO_SECONDS", "120"))

