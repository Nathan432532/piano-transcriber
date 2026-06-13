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


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def ensure_job_dirs() -> None:
    records_dir().mkdir(parents=True, exist_ok=True)
    idempotency_dir().mkdir(parents=True, exist_ok=True)


def records_dir() -> Path:
    return ensure_child_path(config.JOB_DIR, config.JOB_DIR / "records")


def idempotency_dir() -> Path:
    return ensure_child_path(config.JOB_DIR, config.JOB_DIR / "idempotency")


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


def validate_adapter_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise TranscriptionAdapterInferenceError("adapter result must be an object")

    required_fields = {"transcriptUrl", "exports", "noteCount", "durationSeconds"}
    if not required_fields <= set(result):
        raise TranscriptionAdapterInferenceError("adapter result is missing required fields")

    transcript_url = result["transcriptUrl"]
    exports = result["exports"]
    note_count = result["noteCount"]
    duration_seconds = result["durationSeconds"]

    if transcript_url is not None and not isinstance(transcript_url, str):
        raise TranscriptionAdapterInferenceError("adapter transcriptUrl must be null or a string")
    if not isinstance(exports, dict):
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

    return {
        "transcriptUrl": transcript_url,
        "exports": exports,
        "noteCount": note_count,
        "durationSeconds": duration_seconds,
    }


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

    adapter = adapter or DemoTranscriptionAdapter()
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
            update_running_progress(job_id, "loading_model", 25, "Starting deterministic demo engine")
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
            result = validate_adapter_result(result)
        except TranscriptionAdapterInferenceError:
            return fail_transcription_job(job_id, "MODEL_INFERENCE_FAILED", details={"engine": job["engine"]})

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
