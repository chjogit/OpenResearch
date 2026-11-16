"""Shared helpers: canonical hashing, time, strict contracts."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, ConfigDict

KST = timezone(timedelta(hours=9))


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class Integrity(ValueError):
    """Evidence or packet integrity failure. Callers turn this into a held state."""


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(obj):
    return hashlib.sha256(encode(obj).encode('utf-8')).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def instant(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('timezone_required')
    return parsed
