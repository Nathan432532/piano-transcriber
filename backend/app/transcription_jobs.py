from __future__ import annotations

import hashlib
import json
import math
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from . import config
from .audio_validation import ALLOWED_EXTENSIONS, audio_duration_seconds, ensure_child_path
from .transcript import DEMO_TRANSCRIPT


JOB_STATES = {"queued", "running", "succeeded", "failed", "cancelled"}
TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
ALLOWED_TRANSITIONS = {
    "queued": {"running", "cancelled", "failed"},
    "running": {"succeeded", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}

ERROR_CONTRACT: dict[str, tuple[int | None, bool, str]] = {
    "UPLOAD_NOT_FOUND": (404, False, "The uploaded audio could not be found. Upload it again."),
    "UNSUPPORTED_ENGINE": (400, False, "This transcription engine is not available."),
    "INVALID_OPTIONS": (400, False, "Some transcription settings are invalid."),
    "QUEUE_TIMEOUT": (None, True, "The job waited too long. Try again."),
    "TRANSCRIPTION_TIMEOUT": (
        None,
        True,
        "Transcription took too long for this prototype. Try a shorter audio file.",
    ),
    "MODEL_LOAD_FAILED": (None, True, "The transcription engine could not be started."),
    "MODEL_INFERENCE_FAILED": (None, True, "The audio could not be transcribed."),
    "WORKER_LOST": (None, True, "The transcription worker stopped responding. Try again."),
    "CANCELLED": (None, False, "The transcription was cancelled."),
    "JOB_NOT_FOUND": (404, False, "This transcription job no longer exists."),
    "JOB_EXPIRED": (410, False, "This transcription job has expired. Upload the audio again."),
    "JOB_TERMINAL": (409, False, "This job has already finished."),
    "JOB_NOT_SUCCEEDED": (409, False, "Corrections can only be saved for completed transcription jobs."),
    "CORRECTION_REVISION_CONFLICT": (409, False, "This correction is based on an older revision."),
    "INVALID_CORRECTION": (422, False, "The corrected transcript notes are invalid."),
    "IDEMPOTENCY_CONFLICT": (
        409,
        False,
        "This retry does not match the original request. Start a new transcription.",
    ),
    "UNKNOWN_ERROR": (None, True, "Something went wrong during transcription."),
}

_idempotency_locks_guard = threading.Lock()
_idempotency_locks: dict[str, threading.RLock] = {}
_job_locks_guard = threading.Lock()
_job_locks: dict[str, threading.RLock] = {}


class TranscriptionApiError(Exception):
    def __init__(self, code: str, status_code: int | None = None, details: dict[str, Any] | None = None):
        configured_status, retryable, message = ERROR_CONTRACT[code]
        self.code = code
        self.status_code = status_code or configured_status or 500
        self.message = message
        self.retryable = retryable
        self.details = details
        super().__init__(message)

    def to_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            detail["details"] = self.details
        return detail


class InvalidStateTransition(ValueError):
    pass


class TranscriptionAdapterLoadError(Exception):
    pass


class TranscriptionAdapterInferenceError(Exception):
    pass


@dataclass(frozen=True)
class TranscriptionAdapterContext:
    job: dict[str, Any]
    upload_path: Path


@dataclass(frozen=True)
class CorrectedArtifactTransaction:
    transcript_path: Path
    midi_path: Path
    transcript_temp_path: Path
    midi_temp_path: Path


class ProgressReporter(Protocol):
    def __call__(self, phase: str, percent: int, message: str) -> dict[str, Any]:
        ...


class TranscriptionAdapter(Protocol):
    def load(self, context: TranscriptionAdapterContext) -> None:
        ...

    def transcribe(self, context: TranscriptionAdapterContext, report_progress: ProgressReporter) -> dict[str, Any]:
        ...


class DemoTranscriptionAdapter:
    def load(self, context: TranscriptionAdapterContext) -> None:
        pass

    def transcribe(self, context: TranscriptionAdapterContext, report_progress: ProgressReporter) -> dict[str, Any]:
        for phase, percent, message in (
            ("inferencing", 85, "Detecting notes"),
            ("postprocessing", 95, "Normalizing note events"),
            ("saving", 99, "Saving transcript metadata"),
        ):
            report_progress(phase, percent, message)
        return build_demo_result(context.job, context.upload_path)


def create_transcription_adapter() -> TranscriptionAdapter:
    mode = config.TRANSCRIPTION_RUNNER_MODE
    if mode == "demo":
        return DemoTranscriptionAdapter()
    if mode == "basic-pitch":
        from .basic_pitch_adapter import BasicPitchTranscriptionAdapter

        return BasicPitchTranscriptionAdapter(config.BASIC_PITCH_MODEL_PATH)
    raise TranscriptionAdapterLoadError("Unknown transcription runner mode")


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def ensure_job_dirs() -> None:
    records_dir().mkdir(parents=True, exist_ok=True)
    idempotency_dir().mkdir(parents=True, exist_ok=True)
    artifacts_dir().mkdir(parents=True, exist_ok=True)


def records_dir() -> Path:
    return ensure_child_path(config.JOB_DIR, config.JOB_DIR / "records")


def idempotency_dir() -> Path:
    return ensure_child_path(config.JOB_DIR, config.JOB_DIR / "idempotency")


def artifacts_dir() -> Path:
    return ensure_child_path(config.JOB_DIR, config.JOB_DIR / "artifacts")


def job_artifacts_dir(job_id: str) -> Path:
    safe_job_id = validate_job_id(job_id)
    return ensure_child_path(artifacts_dir(), artifacts_dir() / safe_job_id)


def job_path(job_id: str) -> Path:
    safe_job_id = validate_job_id(job_id)
    return ensure_child_path(records_dir(), records_dir() / f"{safe_job_id}.json")


def idempotency_path(idempotency_key: str) -> Path:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return ensure_child_path(idempotency_dir(), idempotency_dir() / f"{digest}.json")


def validate_job_id(job_id: str) -> str:
    try:
        parsed = uuid.UUID(job_id)
    except (ValueError, AttributeError) as exc:
        raise TranscriptionApiError("JOB_NOT_FOUND") from exc
    return str(parsed)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temp_path.replace(path)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temp_path.write_bytes(payload)
    temp_path.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def lock_for_idempotency_key(idempotency_key: str) -> threading.RLock:
    with _idempotency_locks_guard:
        lock = _idempotency_locks.get(idempotency_key)
        if lock is None:
            lock = threading.RLock()
            _idempotency_locks[idempotency_key] = lock
        return lock


def lock_for_job_id(job_id: str) -> threading.RLock:
    safe_job_id = validate_job_id(job_id)
    with _job_locks_guard:
        lock = _job_locks.get(safe_job_id)
        if lock is None:
            lock = threading.RLock()
            _job_locks[safe_job_id] = lock
        return lock


def mutation_lock_for_job(job_id: str) -> threading.RLock:
    job = load_job(job_id)
    idempotency_key = job.get("idempotencyKey")
    if isinstance(idempotency_key, str) and idempotency_key:
        return lock_for_idempotency_key(idempotency_key)
    return lock_for_job_id(job["jobId"])


def make_error(code: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    _, retryable, message = ERROR_CONTRACT[code]
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if details:
        error["details"] = details
    return error


def make_progress(phase: str, percent: int, message: str, updated_at: datetime | None = None) -> dict[str, Any]:
    return {
        "phase": phase,
        "percent": max(0, min(100, int(percent))),
        "message": message,
        "updatedAt": format_timestamp(updated_at or now_utc()),
    }


def canonical_request_body(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "uploadId": body.get("uploadId"),
        "engine": body.get("engine"),
        "options": body.get("options") or {},
    }


def request_hash(body: dict[str, Any]) -> str:
    encoded = json.dumps(canonical_request_body(body), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def idempotency_record_is_fresh(record: dict[str, Any]) -> bool:
    created_at = parse_timestamp(record["createdAt"])
    return created_at + timedelta(seconds=config.TRANSCRIPTION_IDEMPOTENCY_TTL_SECONDS) > now_utc()


def read_fresh_idempotency_record(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        record = read_json(path)
        if not {"jobId", "requestHash", "createdAt"} <= set(record):
            return None
        if not idempotency_record_is_fresh(record):
            return None
        validate_job_id(record["jobId"])
        if not isinstance(record["requestHash"], str):
            return None
        return record
    except (json.JSONDecodeError, OSError, TypeError, ValueError, TranscriptionApiError):
        return None


def find_fresh_job_for_idempotency_key(idempotency_key: str) -> dict[str, Any] | None:
    if not records_dir().exists():
        return None
    for path in records_dir().glob("*.json"):
        try:
            job = read_json(path)
            if job.get("idempotencyKey") != idempotency_key:
                continue
            if "createdAt" not in job or not idempotency_record_is_fresh(job):
                continue
            if not isinstance(job.get("requestHash"), str):
                continue
            return load_job(job["jobId"])
        except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError, TranscriptionApiError):
            continue
    return None


def write_idempotency_record(path: Path, idempotency_key: str, job: dict[str, Any]) -> None:
    atomic_write_json(
        path,
        {
            "idempotencyKey": idempotency_key,
            "jobId": job["jobId"],
            "requestHash": job["requestHash"],
            "createdAt": job["createdAt"],
        },
    )


def validate_options(options: Any) -> dict[str, Any]:
    if options is None:
        return {}
    if not isinstance(options, dict):
        raise TranscriptionApiError("INVALID_OPTIONS")

    normalized = dict(options)
    min_pitch = normalized.get("minPitch")
    max_pitch = normalized.get("maxPitch")
    for value in (min_pitch, max_pitch):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise TranscriptionApiError("INVALID_OPTIONS")

    if min_pitch is not None and not 21 <= min_pitch <= 108:
        raise TranscriptionApiError("INVALID_OPTIONS")
    if max_pitch is not None and not 21 <= max_pitch <= 108:
        raise TranscriptionApiError("INVALID_OPTIONS")
    if min_pitch is not None and max_pitch is not None and min_pitch > max_pitch:
        raise TranscriptionApiError("INVALID_OPTIONS")
    return normalized


def find_upload_path(upload_id: str) -> Path | None:
    if not isinstance(upload_id, str) or not upload_id.isalnum() or len(upload_id) > 64:
        return None
    for extension in ALLOWED_EXTENSIONS:
        candidate = ensure_child_path(config.UPLOAD_DIR, config.UPLOAD_DIR / f"{upload_id}{extension}")
        if candidate.exists():
            return candidate
    return None


def save_job(job: dict[str, Any]) -> dict[str, Any]:
    atomic_write_json(job_path(job["jobId"]), job)
    return deepcopy(job)


def load_job(job_id: str, check_expiry: bool = True) -> dict[str, Any]:
    path = job_path(job_id)
    if not path.exists():
        raise TranscriptionApiError("JOB_NOT_FOUND")
    job = read_json(path)
    if check_expiry and parse_timestamp(job["expiresAt"]) <= now_utc():
        raise TranscriptionApiError("JOB_EXPIRED")
    return job


def create_transcription_job(body: dict[str, Any], idempotency_key: str | None) -> dict[str, Any]:
    if not idempotency_key or not idempotency_key.strip():
        raise TranscriptionApiError("INVALID_OPTIONS")
    normalized_idempotency_key = idempotency_key.strip()

    request_body = canonical_request_body(body)
    request_body["options"] = validate_options(request_body["options"])

    if request_body["engine"] != "basic-pitch":
        raise TranscriptionApiError("UNSUPPORTED_ENGINE")

    upload_path = find_upload_path(request_body["uploadId"])
    if upload_path is None:
        raise TranscriptionApiError("UPLOAD_NOT_FOUND")

    ensure_job_dirs()
    body_hash = request_hash(request_body)
    idem_path = idempotency_path(normalized_idempotency_key)

    with lock_for_idempotency_key(normalized_idempotency_key):
        record = read_fresh_idempotency_record(idem_path)
        if record is not None:
            if record["requestHash"] != body_hash:
                raise TranscriptionApiError("IDEMPOTENCY_CONFLICT")
            job = load_job(record["jobId"])
            job["_created"] = False
            return job

        existing_job = find_fresh_job_for_idempotency_key(normalized_idempotency_key)
        if existing_job is not None:
            if existing_job["requestHash"] != body_hash:
                raise TranscriptionApiError("IDEMPOTENCY_CONFLICT")
            write_idempotency_record(idem_path, normalized_idempotency_key, existing_job)
            existing_job = deepcopy(existing_job)
            existing_job["_created"] = False
            return existing_job

        timestamp = now_utc()
        job_id = str(uuid.uuid4())
        expires_at = timestamp + timedelta(days=config.TRANSCRIPTION_JOB_TTL_DAYS)
        job = {
            "jobId": job_id,
            "uploadId": request_body["uploadId"],
            "engine": request_body["engine"],
            "options": request_body["options"],
            "state": "queued",
            "createdAt": format_timestamp(timestamp),
            "startedAt": None,
            "finishedAt": None,
            "expiresAt": format_timestamp(expires_at),
            "cancelRequestedAt": None,
            "progress": make_progress("queued", 0, "Waiting for worker", timestamp),
            "error": None,
            "result": None,
            "idempotencyKey": normalized_idempotency_key,
            "requestHash": body_hash,
        }
        save_job(job)
        write_idempotency_record(idem_path, normalized_idempotency_key, job)
        created_job = deepcopy(job)
        created_job["_created"] = True
        return created_job


def _transition_job_unlocked(
    job_id: str,
    new_state: str,
    *,
    progress: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if new_state not in JOB_STATES:
        raise InvalidStateTransition(f"Unknown transcription state: {new_state}")

    job = load_job(job_id)
    old_state = job["state"]
    if new_state not in ALLOWED_TRANSITIONS[old_state]:
        raise InvalidStateTransition(f"Transition {old_state} -> {new_state} is not allowed")

    timestamp = now_utc()
    job["state"] = new_state
    if new_state == "running" and job["startedAt"] is None:
        job["startedAt"] = format_timestamp(timestamp)
    if new_state in TERMINAL_STATES:
        job["finishedAt"] = format_timestamp(timestamp)
    if progress is not None:
        current_percent = int(job["progress"]["percent"])
        next_percent = int(progress["percent"])
        if next_percent < current_percent:
            progress = {**progress, "percent": current_percent}
        job["progress"] = progress
    if error is not None:
        job["error"] = error
    if result is not None:
        job["result"] = result
    return save_job(job)


def transition_job(
    job_id: str,
    new_state: str,
    *,
    progress: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with mutation_lock_for_job(job_id):
        return _transition_job_unlocked(job_id, new_state, progress=progress, error=error, result=result)


def claim_transcription_job(job_id: str) -> dict[str, Any]:
    with mutation_lock_for_job(job_id):
        job = load_job(job_id)
        if job["state"] != "queued":
            job = deepcopy(job)
            job["_claimed"] = False
            return job
        claimed = _transition_job_unlocked(
            job_id,
            "running",
            progress=make_progress("validating", 5, "Validating upload"),
        )
        claimed["_claimed"] = True
        return claimed


def update_running_progress(job_id: str, phase: str, percent: int, message: str) -> dict[str, Any]:
    with mutation_lock_for_job(job_id):
        job = load_job(job_id)
        if job["state"] != "running":
            return job
        current_percent = int(job["progress"]["percent"])
        job["progress"] = make_progress(phase, max(current_percent, percent), message)
        return save_job(job)


def fail_transcription_job(
    job_id: str,
    code: str = "UNKNOWN_ERROR",
    *,
    percent: int | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with mutation_lock_for_job(job_id):
        job = load_job(job_id)
        if job["state"] == "queued":
            _transition_job_unlocked(job_id, "running", progress=make_progress("validating", 1, "Validating upload"))
            job = load_job(job_id)
        if job["state"] != "running":
            raise InvalidStateTransition(f"Transition {job['state']} -> failed is not allowed")

        return _transition_job_unlocked(
            job_id,
            "failed",
            progress=make_progress(
                "failed",
                int(percent if percent is not None else job["progress"]["percent"]),
                "Transcription failed",
            ),
            error=make_error(code, details),
        )


def cancel_transcription_job(job_id: str) -> dict[str, Any]:
    with mutation_lock_for_job(job_id):
        job = load_job(job_id)
        if job["state"] in TERMINAL_STATES:
            raise TranscriptionApiError("JOB_TERMINAL", details={"job": public_job(job)})

        timestamp = now_utc()
        job["cancelRequestedAt"] = format_timestamp(timestamp)
        save_job(job)
        return _transition_job_unlocked(
            job_id,
            "cancelled",
            progress=make_progress("cancelled", int(job["progress"]["percent"]), "Transcription cancelled", timestamp),
            error=make_error("CANCELLED"),
        )


def build_demo_result(job: dict[str, Any], upload_path: Path) -> dict[str, Any]:
    duration = round(audio_duration_seconds(upload_path, upload_path.suffix), 3)
    return {
        "transcriptUrl": None,
        "exports": {},
        "noteCount": len(DEMO_TRANSCRIPT["notes"]),
        "durationSeconds": duration,
    }


def artifact_download_url(job_id: str, artifact_name: str) -> str:
    return f"/api/transcriptions/{validate_job_id(job_id)}/artifacts/{artifact_name}"


def validate_transcript_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TranscriptionAdapterInferenceError("adapter transcript must be an object")

    source = value.get("source")
    notes = value.get("notes")
    if not isinstance(value.get("version"), str):
        raise TranscriptionAdapterInferenceError("adapter transcript version must be a string")
    if not isinstance(source, dict):
        raise TranscriptionAdapterInferenceError("adapter transcript source must be an object")
    if not isinstance(notes, list):
        raise TranscriptionAdapterInferenceError("adapter transcript notes must be a list")
    if source.get("kind") not in {"synthetic", "uploaded"}:
        raise TranscriptionAdapterInferenceError("adapter transcript source kind is invalid")
    if not isinstance(source.get("filename"), str):
        raise TranscriptionAdapterInferenceError("adapter transcript filename must be a string")
    if (
        isinstance(source.get("duration"), bool)
        or not isinstance(source.get("duration"), (int, float))
        or not math.isfinite(source["duration"])
        or source["duration"] < 0
    ):
        raise TranscriptionAdapterInferenceError("adapter transcript duration must be a finite non-negative number")

    for note in notes:
        if not isinstance(note, dict):
            raise TranscriptionAdapterInferenceError("adapter transcript notes must be objects")
        normalize_midi_note(note)

    return value


def validate_adapter_result(result: Any, job_id: str | None = None) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise TranscriptionAdapterInferenceError("adapter result must be an object")

    required_fields = {"transcriptUrl", "exports", "noteCount", "durationSeconds"}
    if not required_fields <= set(result):
        raise TranscriptionAdapterInferenceError("adapter result is missing required fields")

    transcript_url = result["transcriptUrl"]
    note_count = result["noteCount"]
    duration_seconds = result["durationSeconds"]

    if transcript_url is not None and not isinstance(transcript_url, str):
        raise TranscriptionAdapterInferenceError("adapter transcriptUrl must be null or a string")
    if not isinstance(result["exports"], dict):
        raise TranscriptionAdapterInferenceError("adapter exports must be an object")
    if isinstance(note_count, bool) or not isinstance(note_count, int) or note_count < 0:
        raise TranscriptionAdapterInferenceError("adapter noteCount must be a non-negative integer")
    if (
        isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, (int, float))
        or not math.isfinite(duration_seconds)
        or duration_seconds < 0
    ):
        raise TranscriptionAdapterInferenceError("adapter durationSeconds must be a finite non-negative number")

    public_result = {
        "transcriptUrl": None,
        "exports": {},
        "noteCount": note_count,
        "durationSeconds": duration_seconds,
    }
    transcript = result.get("_transcript")
    if transcript is not None:
        if job_id is None:
            raise TranscriptionAdapterInferenceError("adapter transcript requires a job id")
        write_transcription_artifacts(job_id, validate_transcript_payload(transcript))
        public_result = public_result_with_existing_artifacts(job_id, public_result)
    return public_result


def public_result_with_existing_artifacts(job_id: str, result: dict[str, Any]) -> dict[str, Any]:
    artifact_dir = job_artifacts_dir(job_id)
    transcript_path = ensure_child_path(artifact_dir, artifact_dir / "transcript.json")
    midi_path = ensure_child_path(artifact_dir, artifact_dir / "transcription.mid")
    next_result = deepcopy(result)
    exports = dict(next_result.get("exports") or {})
    if transcript_path.exists():
        next_result["transcriptUrl"] = artifact_download_url(job_id, "transcript.json")
    else:
        next_result["transcriptUrl"] = None
    if midi_path.exists():
        exports["midi"] = artifact_download_url(job_id, "transcription.mid")
    else:
        exports.pop("midi", None)
    next_result["exports"] = exports
    return next_result


def write_transcription_artifacts(job_id: str, transcript: dict[str, Any]) -> None:
    artifact_dir = job_artifacts_dir(job_id)
    transcript_path = ensure_child_path(artifact_dir, artifact_dir / "transcript.json")
    midi_path = ensure_child_path(artifact_dir, artifact_dir / "transcription.mid")
    atomic_write_json(transcript_path, transcript)
    atomic_write_bytes(midi_path, build_midi_file(transcript["notes"]))


def prepare_corrected_transcription_artifacts(job_id: str, transcript: dict[str, Any]) -> CorrectedArtifactTransaction:
    artifact_dir = job_artifacts_dir(job_id)
    transcript_path = ensure_child_path(artifact_dir, artifact_dir / "corrected-transcript.json")
    midi_path = ensure_child_path(artifact_dir, artifact_dir / "corrected-transcription.mid")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    transcript_temp_path = ensure_child_path(artifact_dir, artifact_dir / f"corrected-transcript.{uuid.uuid4().hex}.tmp")
    midi_temp_path = ensure_child_path(artifact_dir, artifact_dir / f"corrected-transcription.{uuid.uuid4().hex}.tmp")
    try:
        transcript_temp_path.write_text(json.dumps(transcript, indent=2, sort_keys=True) + "\n")
        midi_temp_path.write_bytes(build_midi_file(transcript["notes"]))
        return CorrectedArtifactTransaction(
            transcript_path=transcript_path,
            midi_path=midi_path,
            transcript_temp_path=transcript_temp_path,
            midi_temp_path=midi_temp_path,
        )
    except Exception:
        transcript_temp_path.unlink(missing_ok=True)
        midi_temp_path.unlink(missing_ok=True)
        raise


def cleanup_corrected_transcription_artifacts(transaction: CorrectedArtifactTransaction) -> None:
    transaction.transcript_temp_path.unlink(missing_ok=True)
    transaction.midi_temp_path.unlink(missing_ok=True)


def commit_corrected_transcription_artifacts(transaction: CorrectedArtifactTransaction) -> None:
    replacements = (
        (transaction.transcript_temp_path, transaction.transcript_path),
        (transaction.midi_temp_path, transaction.midi_path),
    )
    backups: list[tuple[Path, Path]] = []
    missing_targets: list[Path] = []

    try:
        for _, target_path in replacements:
            backup_path = target_path.with_name(f"{target_path.name}.{uuid.uuid4().hex}.bak")
            if target_path.exists():
                target_path.replace(backup_path)
                backups.append((target_path, backup_path))
            else:
                missing_targets.append(target_path)

        for temp_path, target_path in replacements:
            temp_path.replace(target_path)
    except Exception:
        for _, target_path in replacements:
            target_path.unlink(missing_ok=True)
        for target_path, backup_path in backups:
            if backup_path.exists():
                backup_path.replace(target_path)
        for target_path in missing_targets:
            target_path.unlink(missing_ok=True)
        raise
    finally:
        for temp_path, _ in replacements:
            temp_path.unlink(missing_ok=True)
        for _, backup_path in backups:
            backup_path.unlink(missing_ok=True)


def get_transcription_artifact_path(job_id: str, artifact_name: str) -> Path:
    artifact_filenames = {
        "transcript.json",
        "transcription.mid",
        "corrected-transcript.json",
        "corrected-transcription.mid",
    }
    if artifact_name not in artifact_filenames:
        raise TranscriptionApiError("JOB_NOT_FOUND")
    job = load_job(job_id)
    result = job.get("result") if job.get("state") == "succeeded" else None
    if not isinstance(result, dict):
        raise TranscriptionApiError("JOB_NOT_FOUND")

    artifact_dir = job_artifacts_dir(job_id)
    path = ensure_child_path(artifact_dir, artifact_dir / artifact_name)
    if not path.exists():
        raise TranscriptionApiError("JOB_NOT_FOUND")

    expected_url = artifact_download_url(job_id, artifact_name)
    if artifact_name == "transcript.json" and result.get("transcriptUrl") != expected_url:
        raise TranscriptionApiError("JOB_NOT_FOUND")
    if artifact_name == "transcription.mid" and (result.get("exports") or {}).get("midi") != expected_url:
        raise TranscriptionApiError("JOB_NOT_FOUND")
    correction = result.get("correction") if isinstance(result.get("correction"), dict) else {}
    correction_exports = correction.get("exports") if isinstance(correction.get("exports"), dict) else {}
    if artifact_name == "corrected-transcript.json" and correction_exports.get("transcript") != expected_url:
        raise TranscriptionApiError("JOB_NOT_FOUND")
    if artifact_name == "corrected-transcription.mid" and correction_exports.get("midi") != expected_url:
        raise TranscriptionApiError("JOB_NOT_FOUND")
    return path


NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name_for_pitch(pitch: int) -> str:
    return f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


def current_correction_revision(job: dict[str, Any]) -> int:
    result = job.get("result")
    if not isinstance(result, dict):
        return 0
    correction = result.get("correction")
    if not isinstance(correction, dict):
        return 0
    revision = correction.get("revision", 0)
    return revision if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0 else 0


def validate_corrected_notes(value: Any, duration_seconds: float | None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TranscriptionApiError("INVALID_CORRECTION", details={"field": "notes"})

    normalized_notes: list[dict[str, Any]] = []
    for index, note in enumerate(value):
        if not isinstance(note, dict):
            raise TranscriptionApiError("INVALID_CORRECTION", details={"field": f"notes[{index}]"})

        pitch = note.get("pitch")
        velocity = note.get("velocity")
        confidence = note.get("confidence")
        start = note.get("startTime")
        end = note.get("endTime")
        hand = note.get("hand")

        if isinstance(pitch, bool) or not isinstance(pitch, int) or not 21 <= pitch <= 108:
            raise TranscriptionApiError("INVALID_CORRECTION", details={"field": f"notes[{index}].pitch"})
        if isinstance(velocity, bool) or not isinstance(velocity, int) or not 1 <= velocity <= 127:
            raise TranscriptionApiError("INVALID_CORRECTION", details={"field": f"notes[{index}].velocity"})
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= float(confidence) <= 1
        ):
            raise TranscriptionApiError("INVALID_CORRECTION", details={"field": f"notes[{index}].confidence"})
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end <= start
        ):
            raise TranscriptionApiError("INVALID_CORRECTION", details={"field": f"notes[{index}].time"})
        if duration_seconds is not None and (float(start) > duration_seconds or float(end) > duration_seconds):
            raise TranscriptionApiError("INVALID_CORRECTION", details={"field": f"notes[{index}].time"})
        if hand != "unknown":
            raise TranscriptionApiError("INVALID_CORRECTION", details={"field": f"notes[{index}].hand"})

        expected_note_name = note_name_for_pitch(pitch)
        note_name = note.get("noteName")
        if note_name is not None and note_name != expected_note_name:
            raise TranscriptionApiError("INVALID_CORRECTION", details={"field": f"notes[{index}].noteName"})

        normalized_notes.append(
            {
                "pitch": pitch,
                "noteName": expected_note_name,
                "startTime": float(start),
                "endTime": float(end),
                "velocity": velocity,
                "confidence": float(confidence),
                "hand": hand,
            }
        )

    return normalized_notes


def save_transcription_corrections(job_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise TranscriptionApiError("INVALID_CORRECTION", details={"field": "body"})
    base_revision = body.get("baseRevision")
    if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision < 0:
        raise TranscriptionApiError("INVALID_CORRECTION", details={"field": "baseRevision"})

    with mutation_lock_for_job(job_id):
        job = load_job(job_id)
        previous_job = deepcopy(job)
        if job["state"] != "succeeded":
            raise TranscriptionApiError("JOB_NOT_SUCCEEDED", details={"state": job["state"]})
        result = job.get("result")
        if not isinstance(result, dict):
            raise TranscriptionApiError("JOB_NOT_SUCCEEDED")

        revision = current_correction_revision(job)
        if base_revision != revision:
            raise TranscriptionApiError(
                "CORRECTION_REVISION_CONFLICT",
                details={"currentRevision": revision},
            )

        duration = result.get("durationSeconds")
        duration_seconds = float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None
        if duration_seconds is not None and not math.isfinite(duration_seconds):
            duration_seconds = None
        notes = validate_corrected_notes(body.get("notes"), duration_seconds)

        next_revision = revision + 1
        transcript = {
            "version": "1.0",
            "source": {
                "kind": "uploaded",
                "filename": f"{job['jobId']}-correction",
                "duration": duration_seconds if duration_seconds is not None else 0,
            },
            "notes": notes,
        }
        artifact_transaction = prepare_corrected_transcription_artifacts(job["jobId"], transcript)

        next_result = deepcopy(result)
        next_result["correction"] = {
            "revision": next_revision,
            "exports": {
                "transcript": artifact_download_url(job["jobId"], "corrected-transcript.json"),
                "midi": artifact_download_url(job["jobId"], "corrected-transcription.mid"),
            },
        }
        job["result"] = next_result
        try:
            save_job(job)
            try:
                commit_corrected_transcription_artifacts(artifact_transaction)
            except Exception:
                save_job(previous_job)
                raise
        except Exception:
            cleanup_corrected_transcription_artifacts(artifact_transaction)
            raise
        return {
            "revision": next_revision,
            "exports": dict(next_result["correction"]["exports"]),
        }


def normalize_midi_note(note: dict[str, Any]) -> dict[str, int]:
    pitch = note.get("pitch")
    start = note.get("startTime")
    end = note.get("endTime")
    velocity = note.get("velocity", 64)
    if isinstance(pitch, bool) or not isinstance(pitch, int) or not 0 <= pitch <= 127:
        raise TranscriptionAdapterInferenceError("adapter transcript note pitch is invalid")
    if isinstance(velocity, bool) or not isinstance(velocity, int) or not 0 <= velocity <= 127:
        raise TranscriptionAdapterInferenceError("adapter transcript note velocity is invalid")
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, (int, float))
        or not isinstance(end, (int, float))
        or not math.isfinite(start)
        or not math.isfinite(end)
        or start < 0
        or end <= start
    ):
        raise TranscriptionAdapterInferenceError("adapter transcript note times are invalid")
    return {
        "pitch": pitch,
        "startTick": seconds_to_midi_ticks(float(start)),
        "endTick": seconds_to_midi_ticks(float(end)),
        "velocity": velocity,
    }


def seconds_to_midi_ticks(seconds: float) -> int:
    ticks_per_second = 480
    return max(0, int(round(seconds * ticks_per_second)))


def encode_variable_length_quantity(value: int) -> bytes:
    if value < 0:
        raise ValueError("MIDI delta time cannot be negative")
    buffer = value & 0x7F
    value >>= 7
    while value:
        buffer <<= 8
        buffer |= (value & 0x7F) | 0x80
        value >>= 7

    output = bytearray()
    while True:
        output.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            break
    return bytes(output)


def build_midi_file(notes: list[dict[str, Any]]) -> bytes:
    events: list[tuple[int, int, bytes]] = []
    for note in notes:
        midi_note = normalize_midi_note(note)
        pitch = midi_note["pitch"]
        velocity = midi_note["velocity"]
        events.append((midi_note["startTick"], 0, bytes((0x90, pitch, velocity))))
        events.append((midi_note["endTick"], 1, bytes((0x80, pitch, 0))))

    track = bytearray()
    track.extend(b"\x00\xff\x51\x03\x07\xa1\x20")
    previous_tick = 0
    for tick, _order, event in sorted(events, key=lambda item: (item[0], item[1])):
        track.extend(encode_variable_length_quantity(tick - previous_tick))
        track.extend(event)
        previous_tick = tick
    track.extend(b"\x00\xff\x2f\x00")

    header = b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + (480).to_bytes(2, "big")
    return header + b"MTrk" + len(track).to_bytes(4, "big") + bytes(track)


def cancel_if_requested(job_id: str) -> dict[str, Any] | None:
    current = load_job(job_id)
    if current["state"] == "cancelled":
        return current
    if current["state"] in TERMINAL_STATES:
        return current
    if current.get("cancelRequestedAt"):
        return cancel_transcription_job(job_id)
    return None


def run_transcription_job(job_id: str, adapter: TranscriptionAdapter | None = None) -> dict[str, Any]:
    job = claim_transcription_job(job_id)
    if not job.get("_claimed"):
        return job

    try:
        upload_path = find_upload_path(job["uploadId"])
        if upload_path is None:
            return fail_transcription_job(job_id, "MODEL_INFERENCE_FAILED", details={"uploadId": job["uploadId"]})

        cancelled = cancel_if_requested(job_id)
        if cancelled is not None:
            return cancelled

        update_running_progress(job_id, "preprocessing", 15, "Preparing audio")
        context = TranscriptionAdapterContext(job=load_job(job_id), upload_path=upload_path)

        cancelled = cancel_if_requested(job_id)
        if cancelled is not None:
            return cancelled

        try:
            adapter = adapter or create_transcription_adapter()
        except TranscriptionAdapterLoadError:
            return fail_transcription_job(job_id, "MODEL_LOAD_FAILED", percent=25, details={"engine": job["engine"]})

        try:
            update_running_progress(job_id, "loading_model", 25, "Starting transcription engine")
            adapter.load(context)
        except TranscriptionAdapterLoadError:
            return fail_transcription_job(job_id, "MODEL_LOAD_FAILED", percent=25, details={"engine": job["engine"]})

        cancelled = cancel_if_requested(job_id)
        if cancelled is not None:
            return cancelled

        try:
            # Blocking inference cannot be interrupted here; cancellation is honored at runner checkpoints.
            result = adapter.transcribe(
                context,
                lambda phase, percent, message: update_running_progress(job_id, phase, percent, message),
            )
        except TranscriptionAdapterInferenceError:
            cancelled = cancel_if_requested(job_id)
            if cancelled is not None:
                return cancelled
            return fail_transcription_job(job_id, "MODEL_INFERENCE_FAILED", details={"engine": job["engine"]})

        cancelled = cancel_if_requested(job_id)
        if cancelled is not None:
            return cancelled

        try:
            result = validate_adapter_result(result, job_id)
        except TranscriptionAdapterInferenceError:
            return fail_transcription_job(job_id, "MODEL_INFERENCE_FAILED", details={"engine": job["engine"]})

        cancelled = cancel_if_requested(job_id)
        if cancelled is not None:
            return cancelled

        return transition_job(
            job_id,
            "succeeded",
            progress=make_progress("complete", 100, "Transcription ready"),
            result=result,
        )
    except InvalidStateTransition:
        raise
    except Exception:
        cancelled = cancel_if_requested(job_id)
        if cancelled is not None:
            return cancelled
        return fail_transcription_job(job_id, "UNKNOWN_ERROR")


def run_demo_transcription_job(job_id: str) -> dict[str, Any]:
    return run_transcription_job(job_id, DemoTranscriptionAdapter())


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "jobId": job["jobId"],
        "uploadId": job["uploadId"],
        "engine": job["engine"],
        "state": job["state"],
        "createdAt": job["createdAt"],
        "startedAt": job["startedAt"],
        "finishedAt": job["finishedAt"],
        "expiresAt": job["expiresAt"],
        "progress": job["progress"],
        "error": job["error"],
        "result": job["result"],
    }


def creation_response(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "jobId": job["jobId"],
        "state": job["state"],
        "progress": job["progress"],
        "links": {
            "self": f"/api/transcriptions/{job['jobId']}",
        },
    }
