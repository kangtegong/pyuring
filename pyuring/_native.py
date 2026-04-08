"""
Compatibility shim: native bindings live in :mod:`pyuring.native`.

Import ``pyuring.native`` for a clearer layout; this name is kept so older
imports ``from pyuring import …`` / ``import pyuring._native`` keep working.
"""

from __future__ import annotations

from pyuring.native import *  # noqa: F403
