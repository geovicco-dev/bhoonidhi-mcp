"""The fuzzy resolver maps casual names to real portal selections.

Runs against a real archive snapshot (tests/fixtures/archive_sample.json) so the
cases reflect the actual Bhoonidhi vocabulary, not invented tokens. Each test
maps to a lesson the resolution spike surfaced.
"""

import json
from pathlib import Path

import pytest

from bhoonidhi_mcp.matching import Vocabulary, resolve_satellite

_ARCHIVE = json.loads(
    (Path(__file__).parent / "fixtures" / "archive_sample.json").read_text()
)


@pytest.fixture(scope="module")
def vocab() -> Vocabulary:
    return Vocabulary.from_archive(_ARCHIVE)


def _sats(resolution) -> list[str]:
    return [s.satellite for s in resolution.selections]


# Lesson 1: a constellation name expands to all its platforms, never just one.
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Sentinel-2", ["Sentinel-2A", "Sentinel-2B", "Sentinel-2C"]),
        ("sentinel 2", ["Sentinel-2A", "Sentinel-2B", "Sentinel-2C"]),
        ("Sentinel-1", ["Sentinel-1A", "Sentinel-1B", "Sentinel-1C", "Sentinel-1D"]),
    ],
)
def test_constellation_expands_to_platforms(vocab, query, expected):
    res = resolve_satellite(query, vocab)
    assert res.is_confident
    assert sorted(_sats(res)) == sorted(expected)


# Lesson 2a: a brand name expands to the whole satellite line.
def test_brand_expands_to_all_platforms(vocab):
    res = resolve_satellite("resourcesat", vocab)
    assert res.is_confident
    assert sorted(_sats(res)) == ["ResourceSat-1", "ResourceSat-2", "ResourceSat-2A"]


# Lesson 2b: a sensor name resolves to the satellites carrying it, sensor pinned.
def test_sensor_name_resolves_to_carriers(vocab):
    res = resolve_satellite("modis", vocab)
    assert res.is_confident
    assert sorted(_sats(res)) == ["Aqua", "Terra"]
    assert all(s.sensor == "MODIS" for s in res.selections)


# Lesson 2c: a bare sensor family with numbered siblings is ambiguous, not a
# guess. "LISS" must not silently pick LISS1 — it offers the variants instead.
def test_bare_sensor_family_returns_variant_candidates(vocab):
    res = resolve_satellite("LISS", vocab)
    assert not res.is_confident
    assert not res.selections
    assert res.candidates == sorted(res.candidates)
    assert "LISS3" in res.candidates
    assert all(c.startswith("LISS") for c in res.candidates)


# A specific numbered sensor variant still resolves confidently.
def test_numbered_sensor_variant_resolves(vocab):
    res = resolve_satellite("LISS3", vocab)
    assert res.is_confident
    assert all(s.sensor == "LISS3" for s in res.selections)
    assert "ResourceSat-2" in _sats(res)


# Lesson 3: glued numeric aliases still resolve after boundary normalization.
@pytest.mark.parametrize("query", ["eos6", "eos-6", "eos 6", "EOS-06"])
def test_glued_numeric_alias_resolves(vocab, query):
    res = resolve_satellite(query, vocab)
    assert res.is_confident
    assert "EOS-06" in _sats(res)


def test_typo_still_resolves(vocab):
    res = resolve_satellite("sentnel-2", vocab)
    assert res.is_confident
    assert "Sentinel-2A" in _sats(res)


def test_single_platform_query(vocab):
    res = resolve_satellite("cartosat 3", vocab)
    assert res.is_confident
    assert "CartoSat-3" in _sats(res)


# Nonsense returns candidates, never a false-confident guess.
def test_nonsense_returns_candidates(vocab):
    res = resolve_satellite("banana", vocab)
    assert not res.is_confident
    assert not res.selections
    assert len(res.candidates) == 3
