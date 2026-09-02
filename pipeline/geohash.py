"""Minimal geohash: encode and the 8 neighbours. Pure Python, no build step."""

from __future__ import annotations

_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_NEIGHBOR = {
    "n": ("p0r21436x8zb9dcf5h7kjnmqesgutwvy", "bc01fg45238967deuvhjyznpkmstqrwx"),
    "s": ("14365h7k9dcfesgujnmqp0r2twvyx8zb", "238967debc01fg45kmstqrwxuvhjyznp"),
    "e": ("bc01fg45238967deuvhjyznpkmstqrwx", "p0r21436x8zb9dcf5h7kjnmqesgutwvy"),
    "w": ("238967debc01fg45kmstqrwxuvhjyznp", "14365h7k9dcfesgujnmqp0r2twvyx8zb"),
}
_BORDER = {
    "n": ("prxz", "bcfguvyz"),
    "s": ("028b", "0145hjnp"),
    "e": ("bcfguvyz", "prxz"),
    "w": ("0145hjnp", "028b"),
}


def encode(lat: float, lon: float, precision: int = 7) -> str:
    lat_lo, lat_hi, lon_lo, lon_hi = -90.0, 90.0, -180.0, 180.0
    out, bit, ch, even = [], 0, 0, True
    while len(out) < precision:
        if even:
            mid = (lon_lo + lon_hi) / 2
            if lon >= mid:
                ch |= 1 << (4 - bit)
                lon_lo = mid
            else:
                lon_hi = mid
        else:
            mid = (lat_lo + lat_hi) / 2
            if lat >= mid:
                ch |= 1 << (4 - bit)
                lat_lo = mid
            else:
                lat_hi = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out.append(_B32[ch])
            bit, ch = 0, 0
    return "".join(out)


def adjacent(h: str, d: str) -> str:
    last, base = h[-1], h[:-1]
    t = len(h) % 2  # 0 even, 1 odd
    if last in _BORDER[d][t] and base:
        base = adjacent(base, d)
    return base + _B32[_NEIGHBOR[d][t].index(last)]


def neighbors(h: str) -> list[str]:
    n, s = adjacent(h, "n"), adjacent(h, "s")
    return [
        n,
        s,
        adjacent(h, "e"),
        adjacent(h, "w"),
        adjacent(n, "e"),
        adjacent(n, "w"),
        adjacent(s, "e"),
        adjacent(s, "w"),
    ]
