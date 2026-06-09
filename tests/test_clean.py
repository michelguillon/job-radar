"""Tests for pipeline.clean."""

from pipeline.clean import clean, normalise, strip_boilerplate, strip_html


def test_strip_html_removes_tags_and_decodes_entities():
    html = "<div><p>Senior&nbsp;Engineer</p><ul><li>Python</li></ul></div>"
    out = strip_html(html)
    assert "<" not in out and ">" not in out
    assert "Senior" in out and "Python" in out


def test_strip_html_empty_returns_empty():
    assert strip_html("") == ""


def test_normalise_collapses_whitespace_and_lowercases():
    assert normalise("  Hello   WORLD\n\tFoo  ") == "hello world foo"


def test_strip_boilerplate_removes_eeo_sentence():
    text = (
        "We build great products. Acme is an equal opportunity employer and "
        "values diversity. Apply now."
    )
    out = strip_boilerplate(text)
    assert "equal opportunity employer" not in out.lower()
    assert "We build great products." in out
    assert "Apply now." in out


def test_strip_boilerplate_removes_accommodation_sentence():
    text = "Role details here. We provide reasonable accommodations on request. End."
    out = strip_boilerplate(text)
    assert "reasonable accommodation" not in out.lower()
    assert "Role details here." in out


def test_clean_full_pipeline():
    html = (
        "<h1>Solutions Engineer</h1>"
        "<p>Work with   APIs.</p>"
        "<footer>BigCo is an equal opportunity employer.</footer>"
    )
    out = clean(html)
    assert out == "solutions engineer work with apis."


def test_clean_is_deterministic():
    html = "<p>Same   Input</p>"
    assert clean(html) == clean(html)
