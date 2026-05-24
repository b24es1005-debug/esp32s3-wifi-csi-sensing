"""Compatibility shim: re-export backend preprocessing.

Supports both execution modes:
- direct script execution from `python/` (absolute import)
- package import (`python` as a package, relative import fallback)
"""

try:
    from backend.preprocessing import *
except ImportError:  # pragma: no cover
    from .backend.preprocessing import *
