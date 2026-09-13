"""
app/utils/procs.py - spawn child processes without flashing a console window.

The packaged app is a windowed build, so it has no console of its own. Every
child started with the default flags therefore gets a brand new one: a black
cmd window that pops up and vanishes. The Snapchat page made this obvious
because it polls its status, and each poll asked node where Chrome is.

CREATE_NO_WINDOW keeps the child headless while still giving us its pipes.
"""

import subprocess
import sys

# Not defined off Windows; the kwargs are simply empty there.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def quiet_kwargs() -> dict:
    """subprocess kwargs that suppress a console window on Windows."""
    if sys.platform != "win32":
        return {}
    return {"creationflags": _NO_WINDOW}
