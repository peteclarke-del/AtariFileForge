"""MSA, DIM and STX containers as ``DiskService`` sees them.

A container session keeps the original file as its working path and parses
it lazily, once, onto the session. Converting one produces a new ``.st``
session holding the sectors the container describes, with a row per track
saying where each came from and whether it arrived intact.

STX is the odd one out: it can be converted from but never to, and the
conversion carries the protection report so the user can see what the
sector image does not hold.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from . import atari_paths
from .dim import DIMError, decode_dim, parse_dim, st_to_dim
from .errors import DiskError
from .image_session import ImageSession
from .msa import MSAError, parse_msa, st_to_msa
from .stx import STXError, decode_stx, parse_stx

#: The container kinds this component owns, with the words used for them.
CONTAINER_KINDS: dict[str, str] = {
    "msa": "Magic Shadow Archiver image",
    "dim": "FastCopy Pro image",
    "stx": "Pasti capture",
}

#: The sector-image formats a container can be converted to.
CONVERSION_FORMATS = ("st", "msa", "dim")


class ContainerDiskMixin:
    """Container parsing and conversion for ``DiskService``."""

    @staticmethod
    def _container(session: ImageSession):
        """Parse the container once and keep the result on the session."""
        if session.container is None:
            data = session.path.read_bytes()
            try:
                if session.kind == "msa":
                    session.container = parse_msa(data)
                elif session.kind == "dim":
                    session.container = parse_dim(data)
                elif session.kind == "stx":
                    session.container = parse_stx(data)
                else:
                    raise DiskError(f"{session.name} is not an MSA, DIM or STX container.")
            except (MSAError, DIMError, STXError) as exc:
                raise DiskError(str(exc)) from exc
        return session.container

    def container_members(self, session: ImageSession) -> list[dict]:
        """The tracks a container holds, as the inspector lists them."""
        parsed = self._container(session)
        if session.kind == "msa":
            return [
                {
                    "name": f"Track {item.track:03d} side {item.side}",
                    "track": item.track,
                    "side": item.side,
                    "length": item.unpacked_length,
                    "packedLength": item.packed_length,
                    "compressed": item.compressed,
                    "complete": True,
                }
                for item in parsed.tracks
            ]
        if session.kind == "dim":
            rows = []
            for track in range(parsed.start_track, parsed.end_track + 1):
                for side in range(parsed.sides):
                    offset = ((track - parsed.start_track) * parsed.sides + side) * parsed.track_size
                    held = max(0, min(parsed.track_size, len(parsed.data) - offset))
                    rows.append(
                        {
                            "name": f"Track {track:03d} side {side}",
                            "track": track,
                            "side": side,
                            "length": parsed.track_size,
                            "packedLength": held,
                            "compressed": False,
                            "complete": held == parsed.track_size,
                        }
                    )
            return rows
        return [
            {
                "name": f"Track {item.track:03d} side {item.side}",
                "track": item.track,
                "side": item.side,
                "length": sum(sector.size for sector in item.sectors),
                "packedLength": sum(len(sector.data or b"") for sector in item.sectors),
                "compressed": False,
                "complete": all(sector.readable for sector in item.sectors),
                "sectors": len(item.sectors),
                "fuzzyBytes": item.fuzzy_size,
            }
            for item in parsed.tracks
        ]

    def _container_member(self, session: ImageSession, inner: str) -> dict:
        name = atari_paths.leaf(inner)
        for item in self.container_members(session):
            if item["name"].casefold() == name.casefold():
                return item
        raise DiskError(f"Container track “{name}” was not found.")

    def container_member_editability(self, session: ImageSession, inner: str) -> dict:
        """Whether one track of a container can be rewritten in place.

        MSA and DIM are plain sectors under a header, so a track is always
        rewritable by converting to ``.st``, editing and converting back. A
        Pasti track is never rewritable: the capture records a physical read
        that no edit can be proved against.
        """
        if session.kind not in CONTAINER_KINDS:
            raise DiskError("Only an MSA, DIM or STX track carries an editability report.")
        member = self._container_member(session, inner)
        if session.kind == "stx":
            return {
                "editable": False,
                "reason": "Pasti captures are read only; convert to .st to edit the sectors.",
                "member": member,
            }
        return {
            "editable": bool(member["complete"]),
            "reason": (
                "" if member["complete"]
                else "The track is not completely present in the container."
            ),
            "member": member,
        }

    def convert_container(
        self, session: ImageSession, disk_format: str
    ) -> tuple[ImageSession, list[dict]]:
        """Rebuild the disk a container describes as a new session.

        A container is a whole floppy, not a bag of files: every track is
        written back where it came from, so the result is the image the
        container was made from rather than a new disk with the same
        contents laid out differently.
        """
        if session.kind not in CONTAINER_KINDS:
            raise DiskError("Only MSA, DIM and STX containers can be converted.")
        if disk_format not in CONVERSION_FORMATS:
            raise DiskError("A container can be converted to ST, MSA or DIM.")
        data = session.path.read_bytes()
        warnings: list[str] = []
        try:
            if session.kind == "msa":
                parsed = parse_msa(data)
                image = parsed.sectors()
                geometry = parsed.geometry
            elif session.kind == "dim":
                parsed = parse_dim(data)
                image, warnings = decode_dim(data)
                geometry = parsed.geometry
            else:
                decoded = decode_stx(data)
                image = decoded.image
                geometry = decoded.geometry
                warnings = list(decoded.warnings)
                warnings.extend(f"Unreadable: {item}" for item in decoded.unreadable[:20])
            if disk_format == "msa":
                payload = st_to_msa(image, geometry)
            elif disk_format == "dim":
                payload = st_to_dim(image, geometry)
            else:
                payload = image
        except (MSAError, DIMError, STXError) as exc:
            raise DiskError(str(exc)) from exc

        stem = Path(session.name).stem or "Disk"
        new_name = self.safe_filename(f"{stem}.{disk_format}")
        folder = self.work_dir / uuid.uuid4().hex
        folder.mkdir(parents=True)
        path = folder / new_name
        path.write_bytes(payload)
        target = self.create_from_path(path)
        for warning in warnings:
            self._append_warning(target, f"{CONTAINER_KINDS[session.kind]}: {warning}")

        rows = [
            {
                "source": member["name"],
                "destination": f"track {member['track']} side {member['side']}",
                "offset": (member["track"] * geometry.sides + member["side"]) * geometry.track_size,
                "length": member["length"],
                "mode": "RLE" if member.get("compressed") else "RAW",
                "complete": member["complete"],
            }
            for member in self.container_members(session)
        ]
        return target, rows


__all__ = ["CONTAINER_KINDS", "CONVERSION_FORMATS", "ContainerDiskMixin"]
