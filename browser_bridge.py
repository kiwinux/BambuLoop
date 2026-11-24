"""JSON boundary for the browser worker's private in-memory filesystem."""

import json
from pathlib import Path

from job_service import INPUT_LIMIT, JobError, JobFiles, dispatch

SESSION = Path("/bambuloop")
STORE = JobFiles(SESSION / "inputs", SESSION / "results", byte_budget=INPUT_LIMIT)
STORE.uploads.mkdir(parents=True, exist_ok=True)
STORE.outputs.mkdir(parents=True, exist_ok=True)


def input_limit_error(size):
    try:
        STORE.check_input_capacity(size)
    except JobError as error:
        return json.dumps(error.payload["error"], ensure_ascii=False)
    return None


def import_one(original):
    staging = SESSION / "incoming"
    try:
        stored = STORE.stage(original)
        staging.replace(STORE.uploads / stored)
        result = STORE.import_staged(original, stored)
    except JobError as error:
        result = {"files": [], "errors": [{"filename": original, "message": error.payload["error"]}]}
    finally:
        staging.unlink(missing_ok=True)
    return json.dumps(result, ensure_ascii=False)


def perform(action, payload):
    status, result = dispatch(STORE, action, json.loads(payload))
    return json.dumps([status, result], ensure_ascii=False, allow_nan=False)
