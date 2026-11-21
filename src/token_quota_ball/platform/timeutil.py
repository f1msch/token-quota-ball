"""Shared timezone used by provider parsers and logs."""

from datetime import timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8))
