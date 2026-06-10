"""api — thin FastAPI layer over the existing CLI write/validation logic (Phase 6).

The HTTP layer mediates browser writes. It imports cli.track (event build/append/
projection) and models.record (vocab + validators); it NEVER calls the scorer,
labeller, or any pipeline stage. Every write is: gate → validate → append → 200.
See api/CLAUDE.md and job_radar_SPEC §10.
"""
