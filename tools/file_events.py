"""Attributed file-mutation tracking for the dashboard's file viewer.

Every working-file mutation (chaos damage, patch heal, reporter restore) flows
through here so a FILE_CHANGED event is published with who changed it and how.
The AI agents NEVER receive these events — they only read raw file text. This
is a human-only overlay, like the baseline: harness ground truth the model can't
see.
"""

from contextlib import contextmanager

from config import ROOT, WRITABLE_FILES


def _rel(path):
    return str(path.resolve().relative_to(ROOT.resolve()))


def _check_writable(path):
    if path.resolve() not in {p.resolve() for p in WRITABLE_FILES}:
        raise ValueError(f"path not writable by agents: {path}")


def emit_file_change(bus, agent, kind, path, before, after):
    """Publish a FILE_CHANGED event. kind in {damage, heal, restore}."""
    bus.emit(
        agent,
        "viewer",
        "FILE_CHANGED",
        f"{agent} {kind} {_rel(path)}",
        {"path": _rel(path), "kind": kind, "before": before, "after": after},
    )


@contextmanager
def track_changes(bus, agent, kind, paths):
    """Snapshot `paths` before a mutation, emit FILE_CHANGED for each that
    actually changed afterward. Rejects non-whitelisted paths up front."""
    for p in paths:
        _check_writable(p)
    before = {p: (p.read_text() if p.exists() else None) for p in paths}
    yield
    for p in paths:
        after = p.read_text() if p.exists() else None
        if after != before[p]:
            emit_file_change(bus, agent, kind, p, before[p], after)
