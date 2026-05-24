"""Compatibility shim: re-export backend utils.

Supports both execution modes:
- direct script execution from `python/` (absolute import)
- package import (`python` as a package, relative import fallback)
"""

try:
	from backend.utils import *
except ImportError:  # pragma: no cover
	from .backend.utils import *

