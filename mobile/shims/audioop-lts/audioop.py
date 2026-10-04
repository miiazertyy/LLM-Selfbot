"""A stand-in for audioop, for the Android app.

Python 3.13 dropped audioop, and discord.py-self imports audioop-lts in its
place, a C extension nobody builds for phones. The library only uses it to
turn the volume of voice audio up or down (audioop.mul), and a phone app never
plays voice, so this does that one thing in plain Python and says plainly that
the rest is not here.
"""
import array
import sys


class error(Exception):
    pass


def mul(fragment, width, factor):
    """Every 16-bit sample times `factor`, clipped to the sample's range."""
    if width != 2:
        raise error("only 16-bit samples are supported here")
    samples = array.array("h")
    samples.frombytes(bytes(fragment))
    if sys.byteorder == "big":
        samples.byteswap()
    out = array.array("h", (max(-32768, min(32767, int(s * factor))) for s in samples))
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


def __getattr__(name):
    raise AttributeError(f"audioop.{name} is not available in the phone app")
