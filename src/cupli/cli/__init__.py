"""CLI surface for cupli.

Composed of small typer apps merged in :mod:`cupli.cli.root`. Each
sub-module covers one area (workspace, lifecycle, exec, hooks, mounts,
diagnostics) so that ``cupli --help`` can group commands and so that each
team area lives in its own file.
"""
