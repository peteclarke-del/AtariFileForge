"""Canonical filename rules for every writable Atari File Forge target.

A GEMDOS name is eight characters, an optional full stop and three more, held
in a fixed eleven-byte field and folded to upper case on the way in. That is
narrow enough that importing anything from a host filesystem means renaming,
so the rules live in one place: what is legal, what an illegal name becomes,
and how a second ``READ.ME`` is given a name of its own.

Uniquifying works on the base rather than the extension, because the
extension is what says which program opens the file. ``LONGNAME.DOC``
becomes ``LONGNAM1.DOC`` and then ``LONGNAM2.DOC``: the base is shortened by
exactly as many characters as the counter needs, so the result still fits the
eight the field allows.
"""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata
from typing import Iterable

from .errors import DiskError


#: The characters GEMDOS refuses inside a name. A space is included: TOS
#: pads the name field with spaces, so one inside a name is indistinguishable
#: from the padding. A full stop is not forbidden, it is the separator.
GEMDOS_FORBIDDEN = frozenset('\\/:*?"<>|+,;=[] ')

_BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: ``NAME.EXT``: eight characters, a full stop and three more.
GEMDOS_BASE_LIMIT = 8
GEMDOS_EXTENSION_LIMIT = 3
GEMDOS_NAME_LIMIT = GEMDOS_BASE_LIMIT + 1 + GEMDOS_EXTENSION_LIMIT

#: Retained under its previous name so existing callers stay stable.
ATARI_NAME_LIMIT = GEMDOS_NAME_LIMIT


def _base36(value: int) -> str:
    digits = []
    while value:
        value, remainder = divmod(value, len(_BASE36))
        digits.append(_BASE36[remainder])
    return "".join(reversed(digits)) or "0"


def _upper(text: str) -> str:
    """Upper-case ASCII letters only, as GEMDOS does.

    The Atari character set is not Latin-1 above 0x7F, so folding an accented
    character here would write a byte the machine reads as something else.
    """
    return "".join(chr(ord(c) - 32) if "a" <= c <= "z" else c for c in text)


@dataclass(frozen=True)
class TargetNamePolicy:
    """Validate, normalise and allocate one target filesystem leaf name."""

    kind: str
    label: str
    limit: int
    forbidden: frozenset[str]
    latin1: bool = False
    #: How the limit reads to a person. A flat target says nothing here; a
    #: GEMDOS volume says ``8.3``.
    form: str = ""

    def public_contract(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "limit": self.limit,
            "forbidden": "".join(sorted(self.forbidden)),
            "latin1": self.latin1,
            "form": self.form,
        }

    def validate(self, value: object) -> str:
        original = str(value or "")
        name = original.strip()
        if not name:
            raise DiskError(f"Enter a {self.label} filename.")
        if name != original:
            raise DiskError(
                f"{self.label} filenames cannot start or end with whitespace."
            )
        if len(name) > self.limit:
            raise DiskError(
                f"{self.label} filenames can contain at most {self.limit} characters."
            )
        if self.latin1:
            try:
                name.encode("latin-1")
            except UnicodeEncodeError as exc:
                raise DiskError(
                    f"{self.label} filenames must use Latin-1 characters."
                ) from exc
        if any(ord(character) < 32 or character in self.forbidden for character in name):
            raise DiskError(
                f"“{name}” contains a character that cannot be used in a "
                f"{self.label} filename."
            )
        return name

    def normalise(self, value: object, fallback: str = "FILE") -> str:
        raw = str(value or "").strip()
        normalised = unicodedata.normalize("NFKC", raw) if self.latin1 else raw
        output: list[str] = []
        for character in normalised:
            if ord(character) < 32 or character in self.forbidden:
                output.append("_")
                continue
            if self.latin1:
                try:
                    character.encode("latin-1")
                except UnicodeEncodeError:
                    output.append("_")
                    continue
            output.append(character)
        candidate = "".join(output)[: self.limit]
        if candidate:
            return candidate
        safe_fallback = "".join(
            character
            for character in (
                unicodedata.normalize("NFKC", str(fallback or "FILE"))
                if self.latin1
                else str(fallback or "FILE")
            )
            if ord(character) >= 32
            and character not in self.forbidden
            and (not self.latin1 or ord(character) <= 0xFF)
        )
        return (safe_fallback or "FILE")[: self.limit]

    def allocate(self, preferred: object, used: Iterable[object]) -> str:
        base = self.normalise(preferred)
        occupied = {str(value or "").casefold() for value in used}
        candidate = base
        suffix = 1
        decimal_capacity = 10 ** (self.limit - 1)
        while candidate.casefold() in occupied:
            if suffix < decimal_capacity:
                decimal = str(suffix)
                candidate = f"{base[: self.limit - len(decimal)]}{decimal}"
            else:
                encoded = suffix - decimal_capacity
                if encoded >= len(_BASE36) ** self.limit:
                    raise DiskError(
                        f"No unused {self.label} filename can be allocated within "
                        f"the {self.limit}-character limit."
                    )
                candidate = _base36(encoded).rjust(self.limit, "0")
            suffix += 1
        return candidate


@dataclass(frozen=True)
class GEMDOSNamePolicy(TargetNamePolicy):
    """The 8.3 rules a FAT volume enforces, base and extension separately."""

    base_limit: int = GEMDOS_BASE_LIMIT
    extension_limit: int = GEMDOS_EXTENSION_LIMIT
    form: str = "8.3"

    def public_contract(self) -> dict:
        contract = super().public_contract()
        contract.update(
            baseLimit=self.base_limit,
            extensionLimit=self.extension_limit,
            caseInsensitive=True,
            upperCase=True,
        )
        return contract

    def _split(self, name: str) -> tuple[str, str]:
        base, _dot, extension = name.partition(".")
        return base, extension

    def validate(self, value: object) -> str:
        original = str(value or "")
        name = original.strip()
        if not name:
            raise DiskError(f"Enter a {self.label} filename.")
        if name != original:
            raise DiskError(
                f"{self.label} filenames cannot start or end with whitespace."
            )
        if name in {".", ".."}:
            raise DiskError(
                "“.” and “..” name a directory itself and its parent, so neither "
                "can be used as a filename."
            )
        bad = sorted(
            {
                character
                for character in name
                if character in self.forbidden or ord(character) < 32 or ord(character) > 255
            }
        )
        if bad:
            shown = " ".join("space" if character == " " else character for character in bad)
            raise DiskError(
                f"A {self.label} filename cannot contain {shown}. Use letters, "
                "digits and ! # $ % & ' ( ) - @ ^ _ ` { } ~ in an 8.3 pattern "
                "such as FOO.PRG."
            )
        base, extension = self._split(name)
        if "." in extension:
            raise DiskError(
                f"“{name}” has more than one full stop. A {self.label} filename is "
                "up to eight characters, one full stop and up to three more."
            )
        if not base:
            raise DiskError(
                f"“{name}” needs at least one character before the full stop."
            )
        if len(base) > self.base_limit:
            raise DiskError(
                f"“{name}” is too long: a {self.label} filename has at most "
                f"{self.base_limit} characters before the full stop."
            )
        if len(extension) > self.extension_limit:
            raise DiskError(
                f"“{name}” is too long: a {self.label} filename has at most "
                f"{self.extension_limit} characters after the full stop."
            )
        upper = _upper(base)
        return f"{upper}.{_upper(extension)}" if extension else upper

    def _clean(self, text: str, limit: int) -> str:
        cleaned = []
        for character in unicodedata.normalize("NFKC", text):
            if character in self.forbidden or ord(character) < 32 or ord(character) > 255:
                cleaned.append("_")
                continue
            cleaned.append(character)
        return _upper("".join(cleaned))[:limit]

    def normalise(self, value: object, fallback: str = "FILE") -> str:
        raw = str(value or "").strip()
        # A host name may hold several full stops. GEMDOS allows one, and the
        # last is the one that says which program opens the file.
        base, _dot, extension = raw.rpartition(".")
        if not base:
            base, extension = raw, ""
        base = self._clean(base.replace(".", "_"), self.base_limit)
        extension = self._clean(extension, self.extension_limit)
        if not base:
            base = self._clean(str(fallback or "FILE"), self.base_limit) or "FILE"
        return f"{base}.{extension}" if extension else base

    def allocate(self, preferred: object, used: Iterable[object]) -> str:
        candidate = self.normalise(preferred)
        occupied = {str(value or "").casefold() for value in used}
        if candidate.casefold() not in occupied:
            return candidate
        base, extension = self._split(candidate)
        suffix = 1
        while True:
            counter = str(suffix)
            if len(counter) >= self.base_limit:
                encoded = _base36(suffix)
                if len(encoded) > self.base_limit:
                    raise DiskError(
                        f"No unused {self.label} filename can be allocated within "
                        f"the {self.form} pattern."
                    )
                stem = encoded.rjust(self.base_limit, "0")
            else:
                stem = f"{base[: self.base_limit - len(counter)]}{counter}"
            attempt = f"{stem}.{extension}" if extension else stem
            if attempt.casefold() not in occupied:
                return attempt
            suffix += 1


def target_name_policy(
    kind: object,
    *,
    item_type: object = "file",
    name_limit: object = None,
) -> TargetNamePolicy:
    """Return the one authoritative leaf-name policy for a target kind."""
    target = str(kind or "").strip().lower()
    row_type = str(item_type or "file").strip().lower()
    if target == "tosrom":
        # A TOS ROM segment is named by the header and the dispatch table
        # inside the image, not by a directory entry, so the only limit is
        # what the report can print.
        return TargetNamePolicy(
            "tosrom", "TOS ROM segment", 60, frozenset(), latin1=True
        )
    if target == "rom":
        return TargetNamePolicy("rom", "ROM bank", 180, frozenset("/"))
    if target == "hd" and row_type in {"partition", "disk", "disk image"}:
        # A partition's label is the volume label written into its own boot
        # sector, which holds eleven characters rather than an 8.3 filename.
        return TargetNamePolicy(
            "hd", "partition label", 11, GEMDOS_FORBIDDEN - {" "}, latin1=True
        )
    if target in {"host", "deployment"}:
        return TargetNamePolicy(target, "host", 255, frozenset("/"))
    try:
        limit = max(1, int(name_limit or GEMDOS_NAME_LIMIT))
    except (TypeError, ValueError):
        limit = GEMDOS_NAME_LIMIT
    return GEMDOSNamePolicy(
        kind=target or "gemdos",
        label="GEMDOS",
        limit=limit,
        forbidden=GEMDOS_FORBIDDEN,
        latin1=True,
    )


def session_name_policy(session) -> TargetNamePolicy:
    # An open partition is an ordinary GEMDOS volume, so it takes the
    # volume's name policy rather than the drive's.
    kind = (
        "gemdos"
        if session.kind == "hd" and getattr(session, "partition", None) is not None
        else session.kind
    )
    capabilities = getattr(session, "gemdos_capabilities", {}) or {}
    return target_name_policy(kind, name_limit=capabilities.get("nameLimit"))


__all__ = [
    "ATARI_NAME_LIMIT",
    "GEMDOS_BASE_LIMIT",
    "GEMDOS_EXTENSION_LIMIT",
    "GEMDOS_FORBIDDEN",
    "GEMDOS_NAME_LIMIT",
    "GEMDOSNamePolicy",
    "TargetNamePolicy",
    "session_name_policy",
    "target_name_policy",
]
