"""Resolve a casual satellite name to exact portal selections.

Users and agents say "Sentinel-2" or "cartosat"; the Bhoonidhi portal searches
on exact satellite tokens like ``Sentinel-2A``. This module bridges that gap
with fuzzy matching (rapidfuzz) over the live archive vocabulary, so the
matcher can never drift from what the portal actually offers.

The vocabulary has three levels a user might name, and the resolver tries each:

- **brand** — "resourcesat" means every ResourceSat platform (1, 2, 2A).
- **family/platform** — "Sentinel-2" is a constellation; the portal lists its
  platforms separately (2A, 2B, 2C), so a family hit expands to all of them.
- **sensor** — "modis" is not a satellite; it names a sensor carried by
  Aqua and Terra, and resolves to those satellites.

A confident match (at or above ``threshold``) resolves to one or more
:class:`~bhoonidhi_downloader.schemas.Selection`. Below the threshold the
resolver returns candidate names instead of guessing, so the agent can ask the
user which they meant. Resolved selections still pass through the downloader's
own ``resolve_selections`` validation downstream — this layer only makes a valid
selection the common case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bhoonidhi_downloader.schemas import Selection
from rapidfuzz import fuzz, process, utils

DEFAULT_THRESHOLD = 88

# A trailing platform letter after a digit distinguishes siblings in a
# constellation: Sentinel-2A vs Sentinel-2B, CartoSat-2S vs CartoSat-2.
_PLATFORM_SUFFIX = re.compile(r"(?<=\d)[A-Z]+$")
# Everything from the first digit onward is the platform designator; stripping
# it leaves the brand shared across a satellite line (ResourceSat-2A -> ResourceSat).
_BRAND_TAIL = re.compile(r"[-_ ]?\d.*$")


@dataclass
class Vocabulary:
    """The satellite/sensor names the portal offers, indexed for matching.

    Built once from an archive listing (``client.archive.list()``) and reused
    across resolutions.
    """

    satellites: list[str]
    families: dict[str, list[str]]  # family key -> platforms, e.g. Sentinel-2 -> [2A,2B,2C]
    brands: dict[str, list[str]]  # brand -> platforms, e.g. ResourceSat -> [1,2,2A]
    sensors: dict[str, list[str]]  # sensor name -> satellites carrying it
    sensor_stems: dict[str, list[str]]  # sensor stem -> variants, e.g. LISS -> [LISS1,..]

    @classmethod
    def from_archive(cls, archive: list[dict[str, Any]]) -> Vocabulary:
        satellites = sorted({r["satName"] for r in archive if r.get("satName")})

        families: dict[str, list[str]] = {}
        brands: dict[str, list[str]] = {}
        for sat in satellites:
            families.setdefault(_family_key(sat), []).append(sat)
            brands.setdefault(_brand_key(sat), []).append(sat)

        sensors: dict[str, list[str]] = {}
        for record in archive:
            sat = record.get("satName")
            if not sat:
                continue
            for sensor in record.get("sensors", []):
                name = sensor.get("senName")
                if name and sat not in sensors.setdefault(name, []):
                    sensors[name].append(sat)

        sensor_stems: dict[str, list[str]] = {}
        for sensor_name in sensors:
            sensor_stems.setdefault(_sensor_stem(sensor_name), []).append(sensor_name)

        return cls(satellites, families, brands, sensors, sensor_stems)


@dataclass
class Resolution:
    """The outcome of resolving one satellite name.

    Exactly one of ``selections`` or ``candidates`` is populated. When the match
    is confident, ``selections`` carries the portal targets to search. When it
    is not, ``candidates`` lists the closest names for the agent to confirm.
    """

    query: str
    selections: list[Selection] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    matched: str | None = None  # the vocabulary key that matched, when confident
    score: float = 0.0

    @property
    def is_confident(self) -> bool:
        return bool(self.selections)


def _family_key(sat: str) -> str:
    """Group constellation siblings: Sentinel-2A/2B/2C -> Sentinel-2."""
    return _PLATFORM_SUFFIX.sub("", sat)


def _brand_key(sat: str) -> str:
    """Group a whole satellite line: ResourceSat-1/2/2A -> ResourceSat."""
    return _BRAND_TAIL.sub("", sat)


def _sensor_stem(sensor: str) -> str:
    """Group numbered sensor siblings: LISS1/LISS3/LISS4(MX23) -> LISS."""
    return _BRAND_TAIL.sub("", sensor)


def _normalize(text: str) -> str:
    """Prepare a query for scoring, separating glued letters and digits.

    ``utils.default_process`` handles case and punctuation, but "eos6" scores
    poorly against "EOS-06" because the digit is glued on. Inserting a boundary
    ("eos6" -> "eos 6") lets the token-aware scorer line them up.
    """
    spaced = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", text)
    return utils.default_process(spaced)


def _best(query: str, choices: list[str]) -> tuple[str, float] | None:
    if not choices:
        return None
    hit = process.extractOne(query, choices, scorer=fuzz.WRatio, processor=_normalize)
    return (hit[0], hit[1]) if hit else None


def resolve_satellite(
    name: str, vocab: Vocabulary, threshold: int = DEFAULT_THRESHOLD
) -> Resolution:
    """Resolve a casual satellite name against the portal vocabulary.

    A query that names a platform number ("Sentinel-2", "cartosat 3") wants that
    specific family, so family is tried first. A brand-only query ("resourcesat")
    wants the whole satellite line, so brand is tried first. This matters because
    a brand can span unrelated constellations — "Sentinel" covers both the
    Sentinel-1 radar and Sentinel-2 optical lines — and only the number tells
    them apart. Sensor names ("modis") are tried last. The first match at or
    above ``threshold`` wins and expands to its selections; if nothing clears the
    bar, the closest satellite names are returned as candidates.
    """
    numbered = bool(re.search(r"\d", name))

    brand = _best(name, list(vocab.brands))

    def try_brand() -> Resolution | None:
        if brand and brand[1] >= threshold and len(vocab.brands[brand[0]]) > 1:
            return _confident(name, vocab.brands[brand[0]], brand)
        return None

    def try_family() -> Resolution | None:
        family = _best(name, list(vocab.families))
        if family and family[1] >= threshold:
            return _confident(name, vocab.families[family[0]], family)
        return None

    def try_single() -> Resolution | None:
        single = _best(name, vocab.satellites)
        if single and single[1] >= threshold:
            return _confident(name, [single[0]], single)
        return None

    def try_sensor() -> Resolution | None:
        sensor = _best(name, list(vocab.sensors))
        if not (sensor and sensor[1] >= threshold):
            return None
        # A no-digit query naming a sensor with numbered siblings (LISS ->
        # LISS1/2/3/4) is ambiguous: the user didn't say which variant, so
        # offer them rather than guessing one. A digit-bearing query
        # ("LISS3") skips this and resolves to the specific variant.
        if not numbered:
            stem = _sensor_stem(sensor[0])
            variants = vocab.sensor_stems.get(stem, [])
            if len(variants) > 1:
                return Resolution(query=name, candidates=sorted(variants))
        res = _confident(name, vocab.sensors[sensor[0]], sensor)
        for sel in res.selections:  # narrow each selection to the named sensor
            sel.sensor = sensor[0]
        return res

    order = (
        (try_family, try_single, try_brand, try_sensor)
        if numbered
        else (try_brand, try_family, try_single, try_sensor)
    )
    for attempt in order:
        result = attempt()
        if result is not None:
            return result

    # Nothing confident — offer the closest satellites for disambiguation.
    near = process.extract(
        name, vocab.satellites, scorer=fuzz.WRatio, processor=_normalize, limit=3
    )
    return Resolution(query=name, candidates=[c[0] for c in near])


def _confident(
    query: str, satellites: list[str], hit: tuple[str, float]
) -> Resolution:
    return Resolution(
        query=query,
        selections=[Selection(satellite=s) for s in satellites],
        matched=hit[0],
        score=hit[1],
    )
