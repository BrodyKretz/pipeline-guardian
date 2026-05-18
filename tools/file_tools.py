from pathlib import Path

from config import ROOT


def _safe(path):
    p = (ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if ROOT.resolve() not in p.parents and p != ROOT.resolve():
        raise ValueError(f"path escapes project root: {path}")
    return p


def read_file(path):
    return _safe(path).read_text()


def write_file(path, content):
    p = _safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"wrote {len(content)} chars to {path}"


def list_files(directory="."):
    d = _safe(directory)
    return sorted(str(p.relative_to(ROOT)) for p in d.iterdir())
