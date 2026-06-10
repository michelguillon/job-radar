"""cli/ — pipeline-stage command-line entry points.

One module per pipeline stage, each a thin CLI over the package logic it drives
(``collectors`` / ``pipeline`` / ``scoring`` / ``models``). Run them as modules
from the repo root so absolute imports and relative corpus paths resolve:

    docker compose run --rm job-radar python -m cli.collect --source all
    docker compose run --rm job-radar python -m cli.score
    docker compose run --rm job-radar python -m cli.track list

This is the operational "CLI writes" surface (CLAUDE.md). One-off corpus
maintenance lives separately under ``scripts/`` (also run as ``python -m
scripts.X``).
"""
