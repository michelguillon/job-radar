"""Tests for collectors.base shared helpers — the client-side cursor filter."""

from __future__ import annotations

import pytest

from collectors.base import passes_cursor


def test_no_cursor_collects_everything():
    assert passes_cursor("2020-01-01T00:00:00Z", None) is True
    assert passes_cursor(None, None) is True


def test_job_at_or_after_cursor_is_kept():
    cutoff = "2026-06-10T00:00:00+00:00"
    assert passes_cursor("2026-06-10T00:00:00+00:00", cutoff) is True  # exactly at cursor
    assert passes_cursor("2026-06-11T09:00:00+00:00", cutoff) is True


def test_job_before_cursor_is_dropped():
    assert passes_cursor("2026-06-09T23:59:59+00:00", "2026-06-10T00:00:00+00:00") is False


def test_timezone_offsets_compared_correctly():
    # 2026-06-10T01:00:00-05:00 == 06:00 UTC, which is after a 00:00 UTC cursor.
    assert passes_cursor("2026-06-10T01:00:00-05:00", "2026-06-10T00:00:00+00:00") is True
    # 2026-06-09T20:00:00-05:00 == 2026-06-10T01:00 UTC vs a 02:00 UTC cursor → before.
    assert passes_cursor("2026-06-09T20:00:00-05:00", "2026-06-10T02:00:00+00:00") is False


@pytest.mark.parametrize("bad", [None, "", "not-a-date", 12345])
def test_unparseable_job_timestamp_is_kept(bad):
    # Never silently drop a job because its own timestamp was missing/malformed.
    assert passes_cursor(bad, "2026-06-10T00:00:00+00:00") is True


def test_fractional_seconds_and_z_suffix_parse():
    assert passes_cursor("2026-06-10T00:00:00.393Z", "2026-06-10T00:00:00+00:00") is True
