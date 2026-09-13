"""
app/version.py - what build this is, and how to compare it with a release.

One constant, imported everywhere, so the About panel, the update check and the
packaged exe can never disagree. Bump `__version__` when cutting a release and
tag the release to match; the comparison strips a leading "v" so `v1.6.0` and
`1.6.0` are the same thing.
"""

import re

__version__ = "1.0.0"


def _parts(value: str) -> tuple:
    """A version as comparable numbers, ignoring anything after them.

    "v1.6.0" and "1.6.0" compare equal. A suffix like "1.6.0-beta.2" compares
    as 1.6.0, which is deliberate: a prerelease of a version is close enough to
    it that telling someone to update would be noise.
    """
    text = str(value or "").strip().lstrip("vV")
    numbers = re.findall(r"\d+", text.split("-")[0].split("+")[0])
    return tuple(int(n) for n in numbers[:4]) or (0,)


def compare(a: str, b: str) -> int:
    """-1 if a is older than b, 0 if the same, 1 if newer."""
    pa, pb = _parts(a), _parts(b)
    # Pad so 1.6 and 1.6.0 are equal rather than one being shorter.
    width = max(len(pa), len(pb))
    pa = pa + (0,) * (width - len(pa))
    pb = pb + (0,) * (width - len(pb))
    return (pa > pb) - (pa < pb)


def is_newer(candidate: str, current: str = None) -> bool:
    """Whether `candidate` is a release worth updating to."""
    if not candidate:
        return False
    return compare(candidate, current or __version__) > 0
