"""Compatibility shim: re-export backend utils.

This top-level module preserves the original import path used by the
existing scripts. It simply imports and re-exports the symbols from
`python/backend/utils.py`.
"""

from .backend.utils import *

