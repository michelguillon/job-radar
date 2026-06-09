"""Root conftest — presence puts the repo root on sys.path so tests can do
`from models.record import ...` regardless of pytest's import mode.
"""
