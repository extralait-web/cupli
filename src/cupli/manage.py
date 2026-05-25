"""Cupli console-script entry point.

The actual command tree lives in :mod:`cupli.cli.root`. This module re-exports
``app`` so that the ``cupli`` console script declared in ``pyproject.toml``
keeps working without a rename.
"""

from cupli.cli.root import app

__all__ = ("app",)
