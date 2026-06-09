"""Tests for pipeline.dedupe."""

from pipeline.dedupe import dedupe, record_hash
from tests.factories import make_record


def test_record_hash_format():
    h = record_hash("some normalised text")
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64
    int(h.split(":", 1)[1], 16)  # hex-decodes without error


def test_record_hash_deterministic():
    assert record_hash("abc") == record_hash("abc")


def test_different_text_different_hash():
    assert record_hash("abc") != record_hash("abd")


def test_dedupe_drops_exact_duplicates_within_batch():
    records = [
        make_record(raw_text="Senior Engineer, Python and SQL"),
        make_record(raw_text="Senior Engineer, Python and SQL"),  # exact dup
        make_record(raw_text="Product Manager, growth"),
    ]
    kept, dropped = dedupe(records, set())
    assert dropped == 1
    assert len(kept) == 2


def test_dedupe_respects_seen_set():
    first = make_record(raw_text="Unique role description")
    kept, _ = dedupe([first], set())
    seen = {first.id}
    # Same content arriving in a later run is dropped.
    again = make_record(raw_text="Unique role description")
    kept2, dropped2 = dedupe([again], seen)
    assert kept2 == [] and dropped2 == 1


def test_dedupe_sets_record_ids():
    rec = make_record(raw_text="Role text here")
    kept, _ = dedupe([rec], set())
    assert kept[0].id == record_hash("role text here")


def test_dedupe_updates_seen_in_place():
    seen = set()
    rec = make_record(raw_text="Another role")
    dedupe([rec], seen)
    assert rec.id in seen


def test_dedupe_normalisation_collapses_whitespace_dupes():
    # Same content differing only in whitespace/case hashes identically.
    records = [
        make_record(raw_text="Hello World"),
        make_record(raw_text="  hello   world  "),
    ]
    kept, dropped = dedupe(records, set())
    assert dropped == 1 and len(kept) == 1


def test_dedupe_uses_html_pipeline_when_present():
    html_rec = make_record(raw_html="<p>Solutions Engineer</p>", raw_text="ignored")
    text_rec = make_record(raw_text="Solutions Engineer")
    kept, dropped = dedupe([html_rec, text_rec], set())
    # HTML-cleaned text equals the plain text, so the second is a duplicate.
    assert dropped == 1 and len(kept) == 1
