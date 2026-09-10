r"""The one place Atari File Forge builds and takes apart inner paths.

GEMDOS separates the components of a path with a backslash and names the root
of a volume with a bare ``\``. That is what TOS prints, what a ``DESKTOP.INF``
line contains and what a program passes to ``Fopen``, so it is the form this
application stores and shows.

Clients do not all speak it. A browser drag, a stored recipe and a saved
workspace may all arrive with forward slashes, and older material may spell
the root ``$``. Every such spelling is accepted and normalised here rather
than being handled again at each call site, so exactly one module knows that
``AUTO/FOO.PRG`` and ``AUTO\FOO.PRG`` name the same file.

Names themselves are 8.3 and case-folded by the filing system, which is why
comparisons elsewhere in the application are case-insensitive. Splitting is
not affected: a full stop separates a name from its extension and never one
component from the next.
"""

from __future__ import annotations

SEPARATOR = "\\"

#: The separator a client may send instead, normalised away on the way in.
ACCEPTED_SEPARATORS = "\\/"

#: Every spelling of "the root of this volume" that the workbench accepts.
ROOT_TOKENS = {"", "\\", "/", ":", "$", "$."}

#: The canonical root, which is the empty path.
ROOT = ""

#: What the user sees when a pane is showing the volume root.
ROOT_DISPLAY = "\\"


def is_root(path: str | None) -> bool:
    """True when this path names the volume root, however it was spelled."""
    return str(path or "").strip() in ROOT_TOKENS


def split(path: str | None) -> list[str]:
    r"""Split an inner path into its components, discarding root spellings.

    Both separators are honoured, because a request may have come from a
    browser that joined its path with forward slashes. A path written ``$.C``
    came from a saved workspace or a bookmark made before the separator was
    settled; it is recognised by its leading ``$`` together with the absence
    of any separator, and is split on full stops just this once so the entry
    it names is still reachable. Nothing writes that form any more.
    """
    text = str(path or "").strip()
    if is_root(text):
        return []
    if text.startswith("$") and not any(part in text for part in ACCEPTED_SEPARATORS):
        return [part for part in text[1:].strip(".").split(".") if part]
    if text.startswith(("$", ":")):
        text = text[1:]
    text = text.replace("/", SEPARATOR)
    return [part for part in text.strip(SEPARATOR).split(SEPARATOR) if part]


def normalise(path: str | None) -> str:
    """Return the canonical form of an inner path."""
    return SEPARATOR.join(split(path))


def join(directory: str | None, name: str) -> str:
    """Join a directory and a leaf name into one inner path."""
    parts = split(directory)
    leaf = str(name).strip(ACCEPTED_SEPARATORS)
    if not leaf:
        return SEPARATOR.join(parts)
    return SEPARATOR.join([*parts, *[part for part in leaf.replace("/", SEPARATOR).split(SEPARATOR) if part]])


def parent(path: str | None) -> str:
    """Return the directory holding this path, or the root."""
    return SEPARATOR.join(split(path)[:-1])


def leaf(path: str | None) -> str:
    """Return the final component of a path, or an empty string at the root."""
    parts = split(path)
    return parts[-1] if parts else ""


def display(path: str | None) -> str:
    """Render a path the way a TOS prompt would, from the volume root."""
    parts = split(path)
    return ROOT_DISPLAY + SEPARATOR.join(parts)


def is_below(path: str | None, directory: str | None) -> bool:
    """True when ``path`` sits inside ``directory`` at any depth.

    The comparison folds case, because GEMDOS stores every name in upper case
    and a client that remembers ``auto\\foo.prg`` is naming the same entry the
    volume calls ``AUTO\\FOO.PRG``.
    """
    branch = [part.casefold() for part in split(directory)]
    parts = [part.casefold() for part in split(path)]
    return parts[: len(branch)] == branch and len(parts) > len(branch)


def depth(path: str | None) -> int:
    return len(split(path))


__all__ = [
    "ACCEPTED_SEPARATORS",
    "ROOT",
    "ROOT_DISPLAY",
    "ROOT_TOKENS",
    "SEPARATOR",
    "depth",
    "display",
    "is_below",
    "is_root",
    "join",
    "leaf",
    "normalise",
    "parent",
    "split",
]
