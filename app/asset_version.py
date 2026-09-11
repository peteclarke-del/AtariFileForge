"""Cache-busting for the page's own scripts and stylesheets.

The page asks for its assets with a version on the query string, which is what
stops a browser serving yesterday's JavaScript from its cache. That version
used to be a literal typed into ``index.html``, so it only changed when
somebody remembered to change it, and the one time it mattered nobody had:
the Python had been updated all day and the page had not moved, so an
operator was running new code underneath an old interface with no sign that
anything was wrong.

It is computed from the files themselves now. Change a script and the version
changes with it; change nothing and it stays put, so caching still works.
"""

from __future__ import annotations

from pathlib import Path

from .checksum import sha256_bytes

#: What the page asks for with a version attached.
VERSIONED_SUFFIXES = (".js", ".css")

#: The placeholder a template carries where the version belongs.
PLACEHOLDER = "__ASSET_VERSION__"


def asset_version(static_dir: Path) -> str:
    """A short digest over every script and stylesheet the page loads.

    The contents are hashed rather than the modification times, so a checkout
    on another machine, or a rebuilt container, produces the same version for
    the same code and does not invalidate a cache for no reason.
    """
    try:
        files = sorted(
            path for path in Path(static_dir).rglob("*")
            if path.is_file() and path.suffix.casefold() in VERSIONED_SUFFIXES
        )
    except OSError:
        return "0"
    parts = bytearray()
    for path in files:
        try:
            parts += path.name.encode("utf-8") + path.read_bytes()
        except OSError:
            continue
    return sha256_bytes(bytes(parts))[:12]


def stamp_index(static_dir: Path, version: str) -> str:
    """The page with its asset version filled in.

    A template that still carries a literal version is rewritten too, so the
    page cannot be served with a stale one whether or not the placeholder has
    reached it yet.
    """
    text = (Path(static_dir) / "index.html").read_text(encoding="utf-8")
    if PLACEHOLDER in text:
        return text.replace(PLACEHOLDER, version)
    import re

    return re.sub(r"\?v=[0-9A-Za-z.\-]+", f"?v={version}", text)


__all__ = ["PLACEHOLDER", "VERSIONED_SUFFIXES", "asset_version", "stamp_index"]
