"""Tests for scoring.profile — load + enum-validate candidate_profile.yaml."""

from pathlib import Path

import pytest

from scoring.profile import (
    Profile,
    ProfileError,
    from_dict,
    load_profile,
    validate_profile,
)

PROFILE_PATH = Path(__file__).resolve().parents[1] / "candidate_profile.yaml"


def _valid_data() -> dict:
    """A minimal, enum-clean profile mapping."""
    return {
        "profile_version": "1.0",
        "last_updated": "2026-06-09",
        "candidate": {
            "search_mode": "selective",
            "target_roles": {"primary": ["Product", "Solutions Engineering"]},
            "target_seniority": ["director", "senior_ic"],
            "target_delivery_motion": ["pre_sales"],
            "target_technical_depth": ["hybrid", "leadership"],
            "acceptable_technical_depth": ["hands_on"],
            "location": {
                "base": "London",
                "acceptable_remote_policy": ["hybrid", "remote"],
                "relocation": False,
            },
            "domains": {
                "strong": ["AdTech"],
                "adjacent": ["AI Platform"],
                "lower_priority": ["Revenue Technology"],
            },
            "requirement_gap_watchlist": ["deep Salesforce administration"],
            "positive_signals": ["enterprise AI platform"],
            "negative_signals": ["pure quota-carrying sales role"],
        },
    }


# --- The real profile on disk ---


def test_real_profile_loads_and_validates():
    profile = load_profile(str(PROFILE_PATH))
    assert isinstance(profile, Profile)
    assert profile.profile_version == "1.0"
    assert profile.search_mode == "selective"
    assert "Solutions Engineering" in profile.target_roles
    assert profile.location_base == "London"
    assert profile.relocation is False
    assert "AdTech" in profile.domains_strong
    assert len(profile.requirement_gap_watchlist) == 8


# --- Validation ---


def test_valid_data_passes():
    assert validate_profile(_valid_data()) == []


def test_from_dict_builds_profile():
    profile = from_dict(_valid_data())
    assert isinstance(profile, Profile)
    assert profile.target_seniority == frozenset({"director", "senior_ic"})
    assert profile.domains_lower == frozenset({"Revenue Technology"})


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda d: d["candidate"]["target_roles"].__setitem__("primary", ["Not A Role"]), "target_roles.primary"),
        (lambda d: d["candidate"].__setitem__("target_seniority", ["principal"]), "target_seniority"),
        (lambda d: d["candidate"]["domains"].__setitem__("strong", ["Crypto"]), "domains.strong"),
        (lambda d: d["candidate"]["location"].__setitem__("acceptable_remote_policy", ["anywhere"]), "acceptable_remote_policy"),
        (lambda d: d["candidate"].__setitem__("target_technical_depth", ["wizard"]), "target_technical_depth"),
        (lambda d: d["candidate"].__setitem__("search_mode", "panic"), "search_mode"),
        (lambda d: d.__delitem__("profile_version"), "profile_version"),
    ],
)
def test_invalid_values_are_reported(mutate, needle):
    data = _valid_data()
    mutate(data)
    errors = validate_profile(data)
    assert any(needle in e for e in errors), f"expected error on {needle}, got {errors}"


def test_load_raises_profile_error_on_bad_enum():
    data = _valid_data()
    data["candidate"]["domains"]["adjacent"] = ["Crypto"]
    with pytest.raises(ProfileError) as exc:
        from_dict(data)
    assert "Crypto" in str(exc.value)


def test_missing_candidate_is_an_error():
    errors = validate_profile({"profile_version": "1.0", "last_updated": "x"})
    assert any("candidate" in e for e in errors)
