"""Tests for pipeline.label — batch submit/poll/download/merge, parse, cost.

The Anthropic client is faked (no network). Pure functions (parse_extraction,
merge_results, estimate_cost, build_system_prompt) are tested directly.
"""

import json

import pytest

from collectors.base import build_raw_record
from models.record import _EXTRACTION_FIELDS
from pipeline import label


def _rec(i: int):
    r = build_raw_record(
        source_url=f"https://x/{i}",
        source_ats="greenhouse",
        company=f"Co{i}",
        collected_at="2026-06-09",
        raw_text=f"Job description {i}",
    )
    r.id = f"sha256:{i:064d}"
    return r


def _full_extraction():
    """A schema-complete extraction dict (all 17 keys present)."""
    return {
        "role_type": ["Product"],
        "seniority": "ic",
        "technical_depth": "hands_on",
        "years_experience_required": "not_stated",
        "required_technologies": ["Python"],
        "required_competencies": [],
        "nice_to_have_technologies": [],
        "nice_to_have_competencies": [],
        "domain": ["SaaS"],
        "remote_policy": "remote",
        "location": "London",
        "delivery_motion": ["direct_delivery"],
        "leadership_geography": [],
        "company_size_signal": "startup",
        "company_stage": "not_stated",
        "culture_signals": [],
        "raw_observations": "",
    }


# --- Fakes mimicking the SDK shapes used by label.py ---


class _Usage:
    def __init__(self):
        self.input_tokens = 100
        self.output_tokens = 50
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 200


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Msg:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage()


class _Result:
    """Wraps result.result.{type, message, error}."""

    def __init__(self, custom_id, type_, *, text=None, error_type=None):
        self.custom_id = custom_id
        self.result = self
        self.type = type_
        self.message = _Msg(text) if text is not None else None
        self.error = type("E", (), {"type": error_type})() if error_type else None


class _Batch:
    def __init__(self, id_, status):
        self.id = id_
        self.processing_status = status


class FakeBatches:
    def __init__(self, *, statuses=None, results=None):
        self._statuses = list(statuses or ["ended"])
        self._results = results or []
        self.created_requests = None

    def create(self, *, requests):
        self.created_requests = requests
        return _Batch("batch_123", self._statuses[0])

    def retrieve(self, batch_id):
        status = self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]
        return _Batch(batch_id, status)

    def results(self, batch_id):
        return iter(self._results)


class FakeClient:
    def __init__(self, batches):
        self.messages = type("M", (), {"batches": batches})()


# --- build_system_prompt ---


def test_system_prompt_includes_enums_and_keys():
    p = label.build_system_prompt()
    assert "series_c_plus" in p  # a company_stage enum value
    assert "Solutions Engineering" in p  # a role_type enum value
    for field in _EXTRACTION_FIELDS:
        assert field in p
    assert "JSON" in p


def test_system_prompt_mentions_ats_metadata_block():
    assert "ATS METADATA" in label.build_system_prompt()


def test_system_prompt_has_role_domain_disambiguation():
    p = label.build_system_prompt()
    assert "Role and domain disambiguation" in p
    # Product Marketing -> GTM, not Product
    assert "Product Marketing" in p and 'NOT "Product"' in p
    # post-sales / CSM is not AI Delivery
    assert 'NOT "AI Delivery"' in p and "Customer Success" in p
    # no Enterprise Software default; empty-list fallback for domain
    assert "Do NOT use it as a default" in p and "empty list []" in p


# --- build_user_content (metadata injection) ---


def test_build_user_content_without_meta_is_just_jd():
    assert label.build_user_content(_rec(0)) == "Job description 0"


def test_build_user_content_prepends_metadata_block():
    meta = {"title": "Solutions Engineer", "location_str": "London", "workplace_type": "hybrid", "country": "GB"}
    out = label.build_user_content(_rec(0), meta)
    assert out.startswith("[ATS METADATA]")
    assert "title: Solutions Engineer" in out
    assert "location_str: London" in out
    assert "[JOB DESCRIPTION]\nJob description 0" in out
    # raw_text itself is never mutated
    assert "[ATS METADATA]" not in _rec(0).raw_text


def test_run_batch_injects_metadata_by_source_url():
    batches = FakeBatches()
    client = FakeClient(batches)
    rec = _rec(0)  # source_url == "https://x/0"
    meta_index = {"https://x/0": {"title": "Forward Deployed Engineer"}}
    label.run_batch([rec], client=client, meta_index=meta_index)
    content = batches.created_requests[0]["params"]["messages"][0]["content"]
    assert "title: Forward Deployed Engineer" in content


# --- run_batch ---


def test_run_batch_keys_requests_by_index_and_returns_id():
    batches = FakeBatches()
    client = FakeClient(batches)
    bid = label.run_batch([_rec(0), _rec(1)], client=client)
    assert bid == "batch_123"
    assert [r["custom_id"] for r in batches.created_requests] == ["rec-0", "rec-1"]


# --- poll_batch ---


def test_poll_batch_waits_until_ended():
    batches = FakeBatches(statuses=["in_progress", "in_progress", "ended"])
    client = FakeClient(batches)
    slept = []
    bid = label.poll_batch("batch_123", client=client, sleep=lambda s: slept.append(s), interval=5)
    assert bid == "batch_123"
    assert slept == [5, 5]  # polled twice before ending


def test_poll_batch_times_out():
    batches = FakeBatches(statuses=["in_progress"])
    client = FakeClient(batches)
    with pytest.raises(TimeoutError):
        label.poll_batch("b", client=client, sleep=lambda s: None, interval=10, max_wait=10)


# --- download_results ---


def test_download_results_shapes_entries():
    results = [
        _Result("rec-0", "succeeded", text=json.dumps(_full_extraction())),
        _Result("rec-1", "errored", error_type="invalid_request"),
    ]
    client = FakeClient(FakeBatches(results=results))
    out = label.download_results("batch_123", client=client)
    assert out[0]["status"] == "succeeded"
    assert out[0]["usage"]["input"] == 100 and out[0]["usage"]["cache_write"] == 200
    assert out[1]["status"] == "errored" and out[1]["error"] == "invalid_request"


# --- parse_extraction ---


def test_parse_extraction_plain_and_with_prose():
    obj = _full_extraction()
    assert label.parse_extraction(json.dumps(obj)) == obj
    wrapped = f"Here is the JSON:\n{json.dumps(obj)}\nDone."
    assert label.parse_extraction(wrapped) == obj


# --- merge_results ---


def test_merge_applies_fields_and_sets_tier():
    records = [_rec(0), _rec(1)]
    results = [
        {"custom_id": "rec-0", "status": "succeeded", "raw_text": json.dumps(_full_extraction())},
        {"custom_id": "rec-1", "status": "errored", "error": "server_error"},
    ]
    labelled, failures = label.merge_results(records, results, tier=4)
    assert len(labelled) == 1 and labelled[0].company == "Co0"
    assert labelled[0].tier == 4
    assert labelled[0].role_type == ["Product"]
    assert labelled[0].seniority == "ic"
    assert len(failures) == 1 and failures[0]["custom_id"] == "rec-1"


def test_merge_produces_schema_valid_record():
    from models.record import validate

    records = [_rec(0)]
    results = [{"custom_id": "rec-0", "status": "succeeded", "raw_text": json.dumps(_full_extraction())}]
    labelled, _ = label.merge_results(records, results, tier=4)
    # annotation defaults are seeded so the labelled record passes full validation
    assert validate(labelled[0]) == []
    assert labelled[0].applied is False
    assert labelled[0].application_decision == "pending"


def test_merge_records_missing_key_as_failure():
    records = [_rec(0)]
    incomplete = _full_extraction()
    del incomplete["seniority"]  # missing required key
    results = [{"custom_id": "rec-0", "status": "succeeded", "raw_text": json.dumps(incomplete)}]
    labelled, failures = label.merge_results(records, results, tier=3)
    assert labelled == []
    assert len(failures) == 1 and "parse" in failures[0]["error"]


# --- estimate_cost ---


def test_estimate_cost_applies_batch_rates():
    results = [
        {"usage": {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_write": 0}},
        {"usage": {"input": 0, "output": 1_000_000, "cache_read": 0, "cache_write": 0}},
    ]
    cost = label.estimate_cost(results)
    # 1M input @ $2.50 + 1M output @ $12.50 = $15.00 (batch rates)
    assert cost["cost_usd"] == pytest.approx(15.0)
    assert cost["tokens"]["input"] == 1_000_000


# --- cli.label.load_records: raw_text population for prefilter survivors ---


def test_load_records_populates_raw_text_from_html(tmp_path):
    """Prefilter survivors carry only raw_html; cli.label.load_records must fill raw_text
    (clean_readable) so the prompt has text — and leave pre-populated raw_text untouched."""
    import cli.label as label_cli

    html_only = build_raw_record(
        source_url="https://x/1", source_ats="greenhouse", company="Acme",
        collected_at="2026-06-09", raw_html="<p>Build the future of AI delivery.</p>",
    )
    pre_clean = build_raw_record(
        source_url="https://x/2", source_ats="greenhouse", company="Acme",
        collected_at="2026-06-09", raw_text="Already cleaned JD text.",
    )
    path = tmp_path / "filtered_20260610.jsonl"
    path.write_text(html_only.to_jsonl() + "\n" + pre_clean.to_jsonl() + "\n", encoding="utf-8")

    loaded = label_cli.load_records(str(path))
    assert "AI delivery" in loaded[0].raw_text             # html-only → raw_text filled
    assert loaded[1].raw_text == "Already cleaned JD text."  # pre-cleaned → left untouched
