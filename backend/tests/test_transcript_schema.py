from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate

from app.transcript import DEMO_TRANSCRIPT


def test_demo_transcript_matches_shared_schema() -> None:
    schema_path = Path(__file__).resolve().parents[2] / "shared" / "transcript.schema.json"
    schema = json.loads(schema_path.read_text())
    validate(instance=DEMO_TRANSCRIPT, schema=schema)


def test_internal_note_shape_is_complete() -> None:
    note = DEMO_TRANSCRIPT["notes"][0]
    assert set(note) == {
        "pitch",
        "noteName",
        "startTime",
        "endTime",
        "velocity",
        "confidence",
        "hand",
    }
    assert note["hand"] == "unknown"
