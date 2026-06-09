"""Tests for the collectors.vc_boards skeleton (Step 5).

All boards are status: requires_js, so collect() must return no records and
must not raise — it only logs each skip.
"""

import logging

from collectors import vc_boards


def _write_boards(tmp_path, boards):
    import yaml

    path = tmp_path / "vc_boards.yaml"
    path.write_text(yaml.safe_dump({"boards": boards}), encoding="utf-8")
    return str(path)


def test_collect_returns_no_records_and_does_not_raise(tmp_path):
    path = _write_boards(
        tmp_path,
        [
            {"name": "Balderton", "status": "requires_js", "platform": "consider", "notes": "SPA"},
            {"name": "Atomico", "status": "requires_js", "platform": "getro", "notes": "SPA"},
        ],
    )
    assert vc_boards.collect(path=path) == []


def test_collect_logs_a_skip_per_board(tmp_path, caplog):
    path = _write_boards(
        tmp_path,
        [
            {"name": "Index Ventures", "status": "requires_js", "platform": "custom", "notes": "Vue"},
        ],
    )
    with caplog.at_level(logging.WARNING):
        vc_boards.collect(path=path)
    skips = [r for r in caplog.records if "SKIP Index Ventures" in r.getMessage()]
    assert len(skips) == 1
    assert "requires_js" in skips[0].getMessage()


def test_real_config_all_requires_js():
    # The committed vc_boards.yaml must have every board skipped (Step 5 gate).
    boards = vc_boards.load_boards()
    assert boards, "vc_boards.yaml has no boards"
    assert all(b["status"] == "requires_js" for b in boards)
    assert vc_boards.collect() == []
