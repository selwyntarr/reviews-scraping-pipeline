"""Name, address and phone normalisation shared by dedupe and matching."""

from __future__ import annotations

import re
import unicodedata

_NAME_STOP = {"the", "inc", "llc", "corp", "co", "ltd", "nyc", "ny", "restaurant", "rest"}
_ORDINAL = re.compile(r"\b(\d+)(st|nd|rd|th)\b")
_STREET_WORDS = {
    "west": "w",
    "east": "e",
    "north": "n",
    "south": "s",
    "avenue": "ave",
    "av": "ave",
    "street": "st",
    "boulevard": "blvd",
    "place": "pl",
    "square": "sq",
    "road": "rd",
    "drive": "dr",
    "lane": "ln",
    "parkway": "pkwy",
    "terrace": "ter",
    "court": "ct",
    "plaza": "plz",
    "saint": "st",
}


def _ascii(s: str) -> str:
    s = s.replace("’", "").replace("'", "")  # McSorley's -> mcsorleys, consistently across sources
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower()


def norm_name(name: str | None) -> str:
    if not name:
        return ""
    s = _ascii(name)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t not in _NAME_STOP]
    return " ".join(tokens)


def norm_street(street: str | None) -> str:
    if not street:
        return ""
    s = _ascii(street)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _ORDINAL.sub(r"\1", s)
    words = [_STREET_WORDS.get(w, w) for w in s.split()]
    return " ".join(words)


def norm_housenumber(hn: str | None) -> str:
    if not hn:
        return ""
    return re.sub(r"[^a-z0-9-]", "", _ascii(hn).split()[0])


def norm_phone(phone: str | None) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def norm_zip(z: str | None) -> str:
    if not z:
        return ""
    m = re.match(r"\d{5}", z.strip())
    return m.group(0) if m else ""
