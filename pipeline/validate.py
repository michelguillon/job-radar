"""Schema validation — split records into schema-valid and failed (job_radar_SPEC §5.3 Step 8).

Pure split over already-parsed records using ``models.record.validate``. Parse-
and schema-version errors are handled by the CLI loader (validate.py), which
turns an unparseable line into a failure entry before this function sees it.
"""

from __future__ import annotations

from models.record import JDRecord, validate


def validate_records(records: list[JDRecord]) -> tuple[list[JDRecord], list[dict]]:
    """Return ``(passed, failed)``.

    ``passed`` is the records with no validation errors; ``failed`` is a list of
    the record's JSONL envelope plus a ``validation_errors`` list.
    """
    passed: list[JDRecord] = []
    failed: list[dict] = []
    for record in records:
        errors = validate(record)
        if errors:
            failed.append({**record.to_dict(), "validation_errors": errors})
        else:
            passed.append(record)
    return passed, failed
