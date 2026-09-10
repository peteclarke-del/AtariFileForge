"""The ``python -m atarinut`` command line and the bulk-copy machinery behind it.

Two audiences share this module. ``main`` is the command line a user or a
script drives. The underscore-prefixed helpers below it are the bulk-copy
implementation, which Atari File Forge borrows through one adapter module so
that a directory copy preserves attribute bits and datestamps without the
workbench re-deriving GEMDOS allocation policy.

Storage order matters. Writing a tree in the order the source stored it keeps
the destination's clusters in the same sequence, which is the difference
between a hard-disk install that loads at full speed on real hardware and one
that seeks for every file. On a FAT volume storage order is simply cluster
order.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..errors import ConfigurationError, DataError
from ..file import (
    AtariMeta,
    format_access_text,
    parse_access_text,
)
from ..file.filetypes import classify, format_filetype
from ..filesystem import (
    AhdiMount,
    create_filesystem,
    create_partitioned_image,
    format_volume,
    identify,
    list_filesystems,
    named_geometry,
    read_partition_table,
    reader_for,
    volume_geometry,
)
from ..filesystem.blocks import NAMED_GEOMETRIES, SECTOR_SIZE
from ..filesystem.gemdos import join_path, split_path
from .mount import mount_image, resolve_mount, split_compound


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------
_NUMBER_RUN = re.compile(r"(\d+)")


def _natural_name_key(name: str):
    """Sort key matching the order the Desktop presents names in.

    Digit runs compare numerically so ``PART2`` sorts before ``PART10``, and
    letters compare case-insensitively because GEMDOS names are.
    """
    parts = _NUMBER_RUN.split(str(name))
    return tuple(
        (1, int(part), "") if index % 2 else (0, 0, part.casefold())
        for index, part in enumerate(parts)
    )


def _in_global_storage_order(source_mount, items: list[dict]) -> list[dict]:
    """Order copy descriptors the way the source volume stores them.

    Directories keep their relative order and always precede their contents;
    files are ordered by their first cluster. Reproducing the source's
    physical order in the destination is what keeps a copied tree compact
    instead of interleaved.
    """
    def key(item: dict):
        if item.get("kind") == "mkdir":
            return (0, item.get("order", 0), _natural_name_key(item.get("dst", "")))
        return (1, int(item.get("block") or 0), _natural_name_key(item.get("dst", "")))

    return sorted(items, key=key)


# ---------------------------------------------------------------------------
# Copy descriptors
# ---------------------------------------------------------------------------
def _file_item(source_mount, source_path: str, destination: str) -> dict:
    """Build one copy descriptor, carrying the source's directory metadata."""
    meta = (
        source_mount.atari_meta(source_path)
        if hasattr(source_mount, "atari_meta")
        else AtariMeta()
    )
    datestamp = meta.datestamp
    if datestamp is None and hasattr(source_mount, "datestamp"):
        try:
            datestamp = source_mount.datestamp(source_path)
        except Exception:
            datestamp = None
    block = 0
    try:
        block = int(source_mount.stat(source_path).block)
    except Exception:
        block = 0
    data = source_mount.read_bytes(source_path)
    return {
        "kind": "file",
        "src": source_path,
        "dst": destination,
        "data": data,
        "attributes": int(meta.attributes) & 0x3F,
        "access": int(meta.attributes) & 0x3F,
        "filetype": classify(source_path, data),
        "datestamp": datestamp,
        "block": block,
        "sourceName": source_path,
    }


def _dir_item(destination: str, order: int) -> dict:
    return {"kind": "mkdir", "dst": destination, "order": order}


def _collect_copy_items(
    source_mount,
    source_inner: str,
    *,
    dst_mount=None,
    dst_bare: str = "",
    dst_slash: bool = False,
    recursive: bool = False,
    wildcards: bool = True,
) -> list[dict]:
    """Collect every copy descriptor for one source path or wildcard.

    ``dst_slash`` says the destination was written as a directory, so a
    single source file lands *inside* it rather than replacing it. That is
    the distinction the Desktop makes when a file is dropped on a folder.
    """
    items: list[dict] = []
    order = 0
    parts = split_path(source_inner)
    parent = join_path(parts[:-1]) if parts else ""
    leaf = parts[-1] if parts else ""

    matches: list[tuple[str, bool]] = []
    if wildcards and leaf and any(character in leaf for character in "*?"):
        for entry in source_mount.iter_entries(parent):
            if fnmatch.fnmatch(entry.name.casefold(), leaf.casefold()):
                matches.append((entry.path, entry.is_dir))
    else:
        stat = source_mount.stat(source_inner)
        matches.append((join_path(parts), stat.is_dir))

    if not matches:
        raise DataError(f"Nothing matched {source_inner}.")

    multiple = len(matches) > 1
    for source_path, is_dir in sorted(matches, key=lambda row: _natural_name_key(row[0])):
        name = split_path(source_path)[-1] if split_path(source_path) else ""
        into_directory = (
            dst_slash
            or multiple
            or (
                dst_mount is not None
                and dst_bare
                and dst_mount.exists(dst_bare)
                and dst_mount.stat(dst_bare).is_dir
            )
        )
        if into_directory and name:
            destination = join_path([*split_path(dst_bare), name])
        else:
            destination = dst_bare or name
        if not is_dir:
            items.append(_file_item(source_mount, source_path, destination))
            continue
        if not recursive:
            raise ConfigurationError(
                f"{source_path} is a directory. Use --recursive to copy its contents."
            )
        items.append(_dir_item(destination, order))
        order += 1
        stack = [(source_path, destination)]
        while stack:
            current_source, current_destination = stack.pop(0)
            for entry in sorted(
                source_mount.iter_entries(current_source),
                key=lambda entry: _natural_name_key(entry.name),
            ):
                child_destination = join_path(
                    [*split_path(current_destination), entry.name]
                )
                if entry.is_dir:
                    items.append(_dir_item(child_destination, order))
                    order += 1
                    stack.append((entry.path, child_destination))
                else:
                    items.append(
                        _file_item(source_mount, entry.path, child_destination)
                    )
    return items


def _ensure_dir_chain(mount, path: str) -> None:
    """Create every missing directory above and including ``path``."""
    parts = split_path(path)
    if not parts:
        return
    for depth in range(1, len(parts) + 1):
        branch = join_path(parts[:depth])
        if not mount.exists(branch):
            mount.mkdir(branch)
        elif not mount.stat(branch).is_dir:
            raise DataError(f"{branch} already exists and is not a directory.")


def _write_copy_item(mount, destination: str, item: dict, overwrite: bool) -> None:
    """Write one copy descriptor into a mounted volume."""
    if mount.exists(destination):
        if not overwrite:
            raise DataError(f"{destination} already exists.")
        mount.remove(destination, force=True)
    _ensure_dir_chain(mount, join_path(split_path(destination)[:-1]))
    attributes = item.get("attributes")
    if attributes is None:
        attributes = item.get("access")
    meta = AtariMeta(
        attributes=int(attributes) if attributes is not None else AtariMeta().attributes,
        datestamp=item.get("datestamp"),
    )
    mount.write_bytes(destination, item["data"], meta)
    datestamp = item.get("datestamp")
    if datestamp is not None and hasattr(mount, "set_datestamp"):
        mount.set_datestamp(destination, datestamp)


def _walk_post_order_mount(mount, path: str) -> list[str]:
    """List a tree children-first, so directories can be removed after them."""
    if not mount.exists(path):
        return []
    if not mount.stat(path).is_dir:
        return [join_path(split_path(path))]
    collected: list[str] = []
    for entry in mount.iter_entries(path):
        if entry.is_dir:
            collected.extend(_walk_post_order_mount(mount, entry.path))
        else:
            collected.append(entry.path)
    collected.append(join_path(split_path(path)))
    return collected


# ---------------------------------------------------------------------------
# Report helpers used by the JSON output
# ---------------------------------------------------------------------------
def _stamp_text(moment: datetime | None) -> str:
    return moment.isoformat(sep="T", timespec="milliseconds") if moment else ""


def _entry_rows(mount, inner: str) -> list[dict]:
    rows: list[dict] = []
    for entry in sorted(mount.iter_entries(inner), key=lambda item: _natural_name_key(item.name)):
        meta = mount.atari_meta(entry.path) if hasattr(mount, "atari_meta") else AtariMeta()
        if entry.is_dir:
            rows.append(
                {
                    "name": entry.name,
                    "type": "dir",
                    "load": "",
                    "exec": "",
                    "attributes": int(meta.attributes),
                    "filetype": "",
                    "datestamp": _stamp_text(meta.datestamp),
                    "length": sum(1 for _child in mount.iter_entries(entry.path)),
                    "attr": format_access_text(meta.access),
                }
            )
            continue
        rows.append(
            {
                "name": entry.name,
                "type": "file",
                "load": int(meta.attributes),
                "exec": 0,
                "attributes": int(meta.attributes),
                "filetype": mount.filetype(entry.path) or "" if hasattr(mount, "filetype") else "",
                "datestamp": _stamp_text(meta.datestamp),
                "length": entry.length,
                "attr": format_access_text(meta.access),
            }
        )
    return rows


def _partition_rows(mount: AhdiMount) -> list[dict]:
    rows: list[dict] = []
    for partition in mount.partitions:
        row = {
            "index": partition.index,
            "name": partition.name,
            "id": partition.id,
            "label": partition.label,
            "type": "dir",
            "load": "",
            "exec": "",
            "filetype": "",
            "datestamp": "",
            "length": partition.size_sectors,
            "attr": "",
            "format": "",
            "bootable": partition.bootable,
            "startSector": partition.start_sector,
            "sizeSectors": partition.size_sectors,
            "sizeBytes": partition.size_bytes,
            "size": partition.size_bytes,
            "free": 0,
        }
        if partition.is_gemdos:
            volume = None
            try:
                volume = mount.open_partition(partition.index)
                row["format"] = volume.format
                row["label"] = volume.title
                row["size"] = volume.size_bytes()
                row["free"] = volume.free_bytes()
            except DataError:
                row["note"] = "unformatted"
            finally:
                if volume is not None:
                    volume.close()
        else:
            row["note"] = f"{partition.id} partition"
        rows.append(row)
    return rows


def _report(rows: list[dict], **metadata) -> dict:
    return {"rows": rows, "metadata": metadata}


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
_SIZE = re.compile(r"(?:capacity=)?([0-9]+(?:\.[0-9]+)?)\s*([kmg]?)(?:i?b)?")


def _parse_size(text: str) -> int:
    """Parse ``20M``, ``512k`` or ``capacity=100MB`` into bytes."""
    request = str(text or "").strip().lower()
    match = _SIZE.fullmatch(request)
    if not match:
        raise ConfigurationError(f"{text!r} is not a size. Use a number with K, M or G.")
    value = float(match.group(1))
    scale = {"": 1, "k": 1024, "m": 1024 * 1024, "g": 1024 * 1024 * 1024}[match.group(2)]
    size = int(value * scale)
    return size - size % SECTOR_SIZE


def _partition(args) -> int | None:
    value = getattr(args, "partition", None)
    return None if value is None else int(value)


def _resolve(args, path: str, *, writable: bool = False):
    return resolve_mount(path, writable=writable, partition=_partition(args))


def command_identify(args) -> int:
    path = Path(args.image)
    rows = [candidate.to_dict() for candidate in identify(path, suffix_hint=path.suffix.lower())]
    if args.output_format == "json":
        _emit({"reports": {"candidates": _report(rows, title=path.name)}})
        return 0
    if not rows:
        raise DataError(f"No supported filing system was found in {path.name}.")
    for row in rows:
        print(f"{row['filesystem']:<10} {row['confidence']:<6} {row['detail']}")
    return 0


def _is_hard_disk_request(args) -> bool:
    if args.filesystem in {"ahdi", "fat16", "hd", "harddisk"}:
        return True
    if args.partitions and int(args.partitions) > 0:
        return True
    return bool(args.size) and not args.format


def command_create(args) -> int:
    path = Path(args.image)
    label = str(args.label or "").strip()
    if args.filesystem == "tosrom":
        raise ConfigurationError("TOS ROM images are not created by this command.")
    if _is_hard_disk_request(args):
        if not args.size:
            raise ConfigurationError("A hard-disk image needs --size, for example --size 32M.")
        size = _parse_size(args.size)
        count = int(args.partitions or 0)
        if args.filesystem == "ahdi" or count > 0:
            count = max(1, count)
            requests = []
            for index in range(count):
                requests.append(
                    {
                        "label": label if count == 1 else (f"{label}{index + 1}" if label else ""),
                        "bootable": bool(args.bootable) and index == 0,
                    }
                )
            disk = create_partitioned_image(path, size, requests, bootable=bool(args.bootable))
            for note in disk.notes:
                sys.stderr.write(f"Note: {note}\n")
            return 0
        # A bare volume the size of a partition, with no table in front.
        with path.open("wb") as handle:
            handle.truncate(size)
        reader = reader_for(path, writable=True)
        try:
            volume = format_volume(
                reader,
                label=label,
                geometry=volume_geometry(size, label=label),
                bootable=bool(args.bootable),
            )
            for note in volume.notes:
                sys.stderr.write(f"Note: {note}\n")
        finally:
            reader.close()
        return 0
    geometry = named_geometry(args.format or "ds-720k")
    with path.open("wb") as handle:
        handle.truncate(geometry.physical_sectors * SECTOR_SIZE)
    reader = reader_for(path, writable=True)
    try:
        format_volume(reader, label=label, geometry=geometry, bootable=bool(args.bootable))
    finally:
        reader.close()
    return 0


def command_format(args) -> int:
    """Format an existing image, or one partition of an AHDI image, in place."""
    image, _inner = split_compound(args.image)
    if not image.is_file():
        raise DataError(f"{image} does not exist.")
    label = str(args.label or "").strip()
    partition = _partition(args)
    reader = reader_for(image, writable=True)
    try:
        target = reader
        if partition is not None:
            disk = read_partition_table(reader)
            chosen = disk.partition(partition)
            target = reader.window(chosen.start_sector, chosen.size_sectors)
        try:
            if args.format:
                geometry = named_geometry(args.format)
            else:
                geometry = volume_geometry(target.length, label=label)
            volume = format_volume(target, label=label, geometry=geometry, bootable=bool(args.bootable))
            for note in volume.notes:
                sys.stderr.write(f"Note: {note}\n")
            print(f"Formatted {volume.format} volume, {volume.size_bytes():,} bytes")
        finally:
            if target is not reader:
                target.close()
    finally:
        reader.close()
    return 0


def command_partitions(args) -> int:
    image, _inner = split_compound(args.image)
    mount, _name = mount_image(image)
    try:
        if not isinstance(mount, AhdiMount):
            raise DataError(f"{image.name} is a bare volume, not a partitioned hard disk.")
        rows = _partition_rows(mount)
        metadata = {
            "title": image.name,
            "description": f"{len(rows)} AHDI partition{'s' if len(rows) != 1 else ''}",
            "scheme": mount.disk.scheme,
            "hdSize": mount.disk.hd_size,
            "bootable": mount.disk.bootable,
            "notes": list(mount.disk.notes),
        }
    finally:
        mount.close()
    if args.output_format == "json":
        _emit({"reports": {"partitions": _report(rows, **metadata)}})
        return 0
    for row in rows:
        status = row.get("note") or row.get("format", "")
        print(
            f"{row['index']:>2} {row['name']:<3} {row['id']} {row['startSector']:>10} "
            f"{row['sizeSectors']:>10} {row['sizeBytes'] // 1024:>9} KiB "
            f"{'boot' if row['bootable'] else '    '} {status} {row.get('label', '')}"
        )
    print(metadata["description"])
    return 0


def command_ls(args) -> int:
    with _resolve(args, args.path) as resolved:
        mount = resolved.mount
        inner = resolved.path
        if isinstance(mount, AhdiMount):
            rows = _partition_rows(mount)
            metadata = {
                "title": resolved.image.name,
                "description": f"{len(rows)} AHDI partition{'s' if len(rows) != 1 else ''}",
                "path": inner,
            }
        else:
            if not mount.exists(inner):
                raise DataError(f"Path not found: {inner or '\\'}")
            if not mount.stat(inner).is_dir:
                raise DataError(f"{inner} is not a directory.")
            rows = _entry_rows(mount, inner)
            files = sum(1 for row in rows if row["type"] == "file")
            used = sum(int(row["length"]) for row in rows if row["type"] == "file")
            metadata = {
                "title": mount.title,
                "description": f"{files} file(s), {used:,} bytes",
                "path": inner,
                "format": getattr(mount, "format", ""),
            }
        if args.output_format == "json":
            _emit({"reports": {"entries": _report(rows, **metadata)}})
            return 0
        print(f"Directory \"{metadata['title']}:\\{inner}\"")
        for row in rows:
            if row["type"] == "dir":
                print(f"{row['name']:<14} <DIR>      {row['attr']:<6} {row['datestamp']}")
            else:
                print(f"{row['name']:<14}{row['length']:>10} {row['attr']:<6} {row['datestamp']}")
        print(metadata["description"])
    return 0


def command_stat(args) -> int:
    image, inner = split_compound(args.path)
    mount, name = mount_image(image, partition=_partition(args))
    try:
        if inner:
            entry = mount.stat(inner)
            rows = [
                {
                    "name": entry.name,
                    "path": entry.path,
                    "type": "dir" if entry.is_dir else "file",
                    "length": entry.length,
                    "blocks": entry.blocks,
                    "cluster": entry.block,
                    "attributes": entry.attributes,
                    "attr": format_access_text(entry.attributes),
                    "datestamp": _stamp_text(entry.datestamp),
                }
            ]
            payload = {"reports": {"entry": _report(rows, title=mount.title)}}
        elif isinstance(mount, AhdiMount):
            rows = _partition_rows(mount)
            payload = {
                "reports": {"partitions": _report(rows, title=image.name)},
                "description": f"{len(rows)} AHDI partition(s)",
            }
        else:
            rows = [
                {
                    "name": mount.title,
                    "format": getattr(mount, "format", name),
                    "size": mount.size_bytes(),
                    "free": mount.free_bytes(),
                    "bootable": bool(mount.boot_option()),
                    "geometry": mount.geometry.to_dict(),
                }
            ]
            payload = {
                "reports": {"volume": _report(rows, title=mount.title)},
                "description": f"{getattr(mount, 'format', name)} volume",
            }
        if args.output_format == "json":
            _emit(payload)
            return 0
        for report in payload["reports"].values():
            for row in report["rows"]:
                print(" ".join(f"{key}={value}" for key, value in row.items() if key != "geometry"))
    finally:
        close = getattr(mount, "close", None)
        if callable(close):
            close()
    return 0


def command_validate(args) -> int:
    image, _inner = split_compound(args.image)
    mount, _name = mount_image(image, partition=_partition(args))
    try:
        if isinstance(mount, AhdiMount):
            problems = list(mount.disk.notes)
            for partition in mount.partitions:
                if not partition.is_gemdos:
                    continue
                try:
                    volume = mount.open_partition(partition.index)
                except DataError as error:
                    problems.append(f"{partition.name} {error}")
                    continue
                try:
                    problems.extend(f"{partition.name} {problem}" for problem in volume.validate())
                finally:
                    volume.close()
        else:
            problems = mount.validate() if hasattr(mount, "validate") else []
    finally:
        close = getattr(mount, "close", None)
        if callable(close):
            close()
    if problems:
        raise DataError("; ".join(problems))
    print("No structural errors found")
    return 0


def command_get(args) -> int:
    with _resolve(args, args.path) as resolved:
        data = resolved.mount.read_bytes(resolved.path)
    if args.destination == "-":
        sys.stdout.buffer.write(data)
    else:
        Path(args.destination).write_bytes(data)
    return 0


def command_put(args) -> int:
    data = sys.stdin.buffer.read() if args.source == "-" else Path(args.source).read_bytes()
    with _resolve(args, args.path, writable=True) as resolved:
        mount = resolved.mount
        _ensure_dir_chain(mount, join_path(split_path(resolved.path)[:-1]))
        meta = AtariMeta(access=parse_access_text(args.attributes)) if args.attributes else None
        if mount.exists(resolved.path):
            mount.remove(resolved.path, force=True)
        mount.write_bytes(resolved.path, data, meta)
        mount.flush()
    return 0


def command_cp(args) -> int:
    source_image, source_inner = split_compound(args.source)
    target_image, target_inner = split_compound(args.destination)
    destination_slash = args.destination.endswith(("/", "\\", ":"))
    partition = _partition(args)
    source_mount, _ = mount_image(source_image, partition=partition)
    try:
        if source_image == target_image:
            target_mount, _ = mount_image(target_image, writable=True, partition=partition)
            source_mount.close()
            source_mount = target_mount
        else:
            target_mount, _ = mount_image(target_image, writable=True, partition=partition)
        try:
            items = _collect_copy_items(
                source_mount,
                source_inner,
                dst_mount=target_mount,
                dst_bare=join_path(split_path(target_inner)),
                dst_slash=destination_slash,
                recursive=bool(args.recursive),
                wildcards=not args.no_wildcards,
            )
            for item in _in_global_storage_order(source_mount, items):
                if item["kind"] == "mkdir":
                    _ensure_dir_chain(target_mount, item["dst"])
                else:
                    _write_copy_item(target_mount, item["dst"], item, bool(args.force))
            target_mount.flush()
        finally:
            if target_mount is not source_mount:
                target_mount.close()
    finally:
        source_mount.close()
    return 0


def command_mv(args) -> int:
    """Rename or move an entry inside one image.

    The destination is an inner path, not a second compound path: a move
    between two images is a copy followed by a delete, which is what ``cp``
    and ``rm`` are for.
    """
    _image, source_inner = split_compound(args.source)
    destination = args.destination
    if ":" in destination and not re.match(r"^[A-Za-z]:", destination):
        _target_image, destination = split_compound(destination)
    with _resolve(args, args.source, writable=True) as resolved:
        resolved.mount.rename(source_inner, destination)
        resolved.mount.flush()
    return 0


def command_rm(args) -> int:
    """Delete one or several entries from the same image in one open."""
    first, *_rest = args.paths
    image, _inner = split_compound(first)
    inners = [split_compound(path)[1] for path in args.paths]
    with _resolve(args, str(image), writable=True) as resolved:
        mount = resolved.mount
        for inner in inners:
            targets = (
                _walk_post_order_mount(mount, inner) if args.recursive else [inner]
            )
            for path in targets:
                mount.remove(path, force=bool(args.force), recursive=False)
        mount.flush()
    return 0


def command_mkdir(args) -> int:
    with _resolve(args, args.path, writable=True) as resolved:
        _ensure_dir_chain(resolved.mount, resolved.path)
        resolved.mount.flush()
    return 0


def command_opt(args) -> int:
    with _resolve(args, args.image, writable=args.option is not None) as resolved:
        mount = resolved.mount
        if args.option is None:
            print(mount.boot_option())
            return 0
        mount.set_boot_option(int(args.option))
        mount.flush()
    return 0


def command_title(args) -> int:
    with _resolve(args, args.path, writable=args.title is not None) as resolved:
        node = resolved.mount._navigate(resolved.path)
        if args.title is None:
            print(node.title)
            return 0
        node.set_title(args.title)
        resolved.mount.flush()
    return 0


def command_chmod(args) -> int:
    with _resolve(args, args.path, writable=True) as resolved:
        resolved.mount.set_access(resolved.path, parse_access_text(args.flags))
        resolved.mount.flush()
    return 0


def command_lock(args) -> int:
    with _resolve(args, args.path, writable=True) as resolved:
        access = resolved.mount.access(resolved.path)
        resolved.mount.set_access(resolved.path, access.with_locked(True))
        resolved.mount.flush()
    return 0


def command_unlock(args) -> int:
    with _resolve(args, args.path, writable=True) as resolved:
        access = resolved.mount.access(resolved.path)
        resolved.mount.set_access(resolved.path, access.with_locked(False))
        resolved.mount.flush()
    return 0


def command_compact(args) -> int:
    with _resolve(args, args.image, writable=True) as resolved:
        moved = resolved.mount.defragment()
        resolved.mount.flush()
    print(f"{moved} cluster(s) moved")
    return 0


def command_tree(args) -> int:
    with _resolve(args, args.path) as resolved:
        mount = resolved.mount

        def walk(path: str, depth: int) -> None:
            for entry in sorted(mount.iter_entries(path), key=lambda item: _natural_name_key(item.name)):
                marker = "\\" if entry.is_dir else ""
                print(f"{'  ' * depth}{entry.name}{marker}")
                if entry.is_dir:
                    walk(entry.path, depth + 1)

        walk(resolved.path, 0)
    return 0


def command_find(args) -> int:
    with _resolve(args, args.path) as resolved:
        mount = resolved.mount
        pattern = args.pattern.casefold()

        def walk(path: str) -> None:
            for entry in mount.iter_entries(path):
                if fnmatch.fnmatch(entry.name.casefold(), pattern):
                    print(entry.path)
                if entry.is_dir:
                    walk(entry.path)

        walk(resolved.path)
    return 0


def command_freemap(args) -> int:
    with _resolve(args, args.image) as resolved:
        flags = resolved.mount.free_map()
        width = 64
        for start in range(0, len(flags), width):
            row = flags[start : start + width]
            print(f"{start + 2:>8} " + "".join("." if free else "#" for free in row))
        print(f"{sum(flags):,} free of {len(flags):,} clusters")
    return 0


def command_export(args) -> int:
    destination = Path(args.destination)
    destination.mkdir(parents=True, exist_ok=True)
    with _resolve(args, args.path) as resolved:
        mount = resolved.mount

        def walk(path: str, target: Path) -> None:
            target.mkdir(parents=True, exist_ok=True)
            for entry in mount.iter_entries(path):
                if entry.is_dir:
                    walk(entry.path, target / entry.name)
                else:
                    (target / entry.name).write_bytes(mount.read_bytes(entry.path))

        walk(resolved.path, destination)
    return 0


def command_import(args) -> int:
    source = Path(args.source)
    if not source.is_dir():
        raise ConfigurationError(f"{source} is not a directory.")
    with _resolve(args, args.path, writable=True) as resolved:
        mount = resolved.mount
        for item in sorted(source.rglob("*")):
            relative = item.relative_to(source)
            inner = join_path([*split_path(resolved.path), *relative.parts])
            if item.is_dir():
                _ensure_dir_chain(mount, inner)
            else:
                _ensure_dir_chain(mount, join_path(split_path(inner)[:-1]))
                if mount.exists(inner):
                    mount.remove(inner, force=True)
                mount.write_bytes(inner, item.read_bytes())
        mount.flush()
    return 0


def command_cat(args) -> int:
    with _resolve(args, args.path) as resolved:
        sys.stdout.buffer.write(resolved.mount.read_bytes(resolved.path))
    return 0


def command_type(args) -> int:
    with _resolve(args, args.path) as resolved:
        data = resolved.mount.read_bytes(resolved.path)
    sys.stdout.write(data.decode("latin-1").replace("\r\n", "\n").replace("\r", "\n"))
    return 0


def command_get_datestamp(args) -> int:
    with _resolve(args, args.path) as resolved:
        stamp = resolved.mount.datestamp(resolved.path)
    print(_stamp_text(stamp))
    return 0


def command_set_datestamp(args) -> int:
    moment = (
        datetime.now(timezone.utc)
        if args.value in {"now", None}
        else datetime.fromisoformat(args.value)
    )
    with _resolve(args, args.path, writable=True) as resolved:
        resolved.mount.set_datestamp(resolved.path, moment)
        resolved.mount.flush()
    return 0


def command_filetype(args) -> int:
    with _resolve(args, args.path) as resolved:
        data = resolved.mount.read_bytes(resolved.path)
    print(format_filetype(classify(resolved.path, data)))
    return 0


def command_storage_order(args) -> int:
    with _resolve(args, args.path) as resolved:
        mount = resolved.mount
        rows = []

        def walk(path: str) -> None:
            for entry in mount.iter_entries(path):
                if entry.is_dir:
                    walk(entry.path)
                else:
                    rows.append((entry.block, entry.path, entry.length))

        walk(resolved.path)
        for block, path, length in sorted(rows):
            print(f"{block:>8} {length:>10} {path}")
    return 0


def command_list_filesystems(args) -> int:
    for row in list_filesystems():
        print(f"{row['name']:<10} {row['label']}")
    return 0


def command_describe_filesystem(args) -> int:
    driver = create_filesystem(args.name)
    print(f"{driver.name}: {driver.label}")
    if driver.name in {"gemdos", "fat12", "fat16"}:
        print("Floppy formats: " + ", ".join(sorted(NAMED_GEOMETRIES)))
    return 0


def command_tosrom(args) -> int:
    from ..tosrom import TOSRom

    rom = TOSRom(Path(args.image).read_bytes())
    if args.output_format == "json":
        _emit(rom.to_dict())
        return 0
    header = rom.header
    print(f"{rom.release}, {len(rom.data) // 1024} KiB at ${rom.base:06X}")
    print(
        f"{header.country} {header.video_standard}, {header.machine}, "
        f"built {header.date.isoformat() if header.date else 'unknown date'}"
    )
    for segment in rom.segments:
        print(
            f"  {segment.name:<8} ${segment.start:06X} {segment.length:>8} bytes  "
            f"{'proven' if segment.proven else 'unsegmented'}: {segment.evidence}"
        )
    for point in rom.entry_points:
        print(f"  {point.name:<36} ${point.address:06X}  {point.evidence}")
    return 0



# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m atarinut",
        description="Work with GEMDOS floppies, AHDI partitioned hard disks and TOS ROM images.",
    )
    parser.add_argument("--version", action="store_true", help="Show the engine version and exit.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Re-raise engine errors after printing them, so the traceback is visible.",
    )
    commands = parser.add_subparsers(dest="command")

    def add(name, handler, help_text, *, partition=True):
        sub = commands.add_parser(name, help=help_text)
        sub.set_defaults(handler=handler)
        if partition:
            sub.add_argument(
                "--partition",
                type=int,
                default=None,
                help="Select one partition of an AHDI hard-disk image (0 is C:).",
            )
        return sub

    sub = add("identify", command_identify, "Identify an image's filing system by content.", partition=False)
    sub.add_argument("--as", dest="output_format", default="text", choices=("text", "json"))
    sub.add_argument("image")

    sub = add("create", command_create, "Create a new empty image.", partition=False)
    sub.add_argument("--filesystem", default="gemdos", help="gemdos (default) or ahdi.")
    sub.add_argument(
        "--format",
        default=None,
        help="Floppy format: " + ", ".join(sorted(NAMED_GEOMETRIES)) + ". Default ds-720k.",
    )
    sub.add_argument("--label", default="", help="Volume label, up to 11 characters.")
    sub.add_argument("--size", default=None, help="Hard-disk image size, for example 32M.")
    sub.add_argument("--partitions", type=int, default=0, help="Number of AHDI partitions.")
    sub.add_argument("--bootable", action="store_true", help="Make the boot sector executable.")
    sub.add_argument("image")

    sub = add("format", command_format, "Format an existing image or partition in place.")
    sub.add_argument("--format", default=None, help="Floppy format name; default fits the image size.")
    sub.add_argument("--label", default="")
    sub.add_argument("--bootable", action="store_true")
    sub.add_argument("image")

    sub = add("partitions", command_partitions, "List the partitions of an AHDI hard-disk image.", partition=False)
    sub.add_argument("--as", dest="output_format", default="text", choices=("text", "json"))
    sub.add_argument("image")

    sub = add("ls", command_ls, "List directory contents.")
    sub.add_argument("--as", dest="output_format", default="text", choices=("text", "json"))
    sub.add_argument("path")

    sub = add("stat", command_stat, "Volume summary, or metadata for one path.")
    sub.add_argument("--as", dest="output_format", default="text", choices=("text", "json"))
    sub.add_argument("path")

    sub = add("validate", command_validate, "Check an image's structure for inconsistencies.")
    sub.add_argument("image")

    sub = add("get", command_get, "Export a file from an image to the host.")
    sub.add_argument("--meta-format", default="none")
    sub.add_argument("path")
    sub.add_argument("destination")

    sub = add("put", command_put, "Import a host file into an image.")
    sub.add_argument(
        "--attributes",
        "--attr",
        dest="attributes",
        default=None,
        help="Attribute bits as rhsvda text, letters to set, or a number.",
    )
    sub.add_argument("source")
    sub.add_argument("path")

    sub = add("cp", command_cp, "Copy files or a tree within or between images.")
    sub.add_argument("--recursive", action="store_true")
    sub.add_argument("--force", action="store_true")
    sub.add_argument("--no-wildcards", action="store_true")
    sub.add_argument("--order", default=None)
    sub.add_argument("source")
    sub.add_argument("destination")

    sub = add("mv", command_mv, "Rename or move an entry inside an image.")
    sub.add_argument("source")
    sub.add_argument("destination")

    sub = add("rm", command_rm, "Delete entries from an image.")
    sub.add_argument("--recursive", action="store_true")
    sub.add_argument("--force", action="store_true")
    sub.add_argument("paths", nargs="+")

    sub = add("mkdir", command_mkdir, "Create a directory.")
    sub.add_argument("path")

    sub = add("opt", command_opt, "Read or set whether the boot sector is executable.")
    sub.add_argument("image")
    sub.add_argument("option", nargs="?", default=None)

    sub = add("title", command_title, "Read or set the volume label.")
    sub.add_argument("path")
    sub.add_argument("title", nargs="?", default=None)

    sub = add("chmod", command_chmod, "Set attribute bits (rhsvda text or a number).")
    sub.add_argument("path")
    sub.add_argument("flags")

    sub = add("lock", command_lock, "Set the read-only bit on an entry.")
    sub.add_argument("path")

    sub = add("unlock", command_unlock, "Clear the read-only bit on an entry.")
    sub.add_argument("path")

    sub = add("compact", command_compact, "Rewrite fragmented files so their clusters are contiguous.")
    sub.add_argument("image")

    sub = add("tree", command_tree, "Display a recursive directory tree.")
    sub.add_argument("path")

    sub = add("find", command_find, "Find entries matching a pattern.")
    sub.add_argument("path")
    sub.add_argument("pattern")

    sub = add("freemap", command_freemap, "Show which clusters are free.")
    sub.add_argument("image")

    sub = add("export", command_export, "Bulk-export an image to a host directory.")
    sub.add_argument("path")
    sub.add_argument("destination")

    sub = add("import", command_import, "Bulk-import a host directory into an image.")
    sub.add_argument("source")
    sub.add_argument("path")

    sub = add("cat", command_cat, "Write a file's raw bytes to standard output.")
    sub.add_argument("path")

    sub = add("type", command_type, "Display a text file with host line endings.")
    sub.add_argument("path")

    sub = add("get-datestamp", command_get_datestamp, "Print an entry's datestamp.")
    sub.add_argument("path")

    sub = add("set-datestamp", command_set_datestamp, "Set an entry's datestamp.")
    sub.add_argument("path")
    sub.add_argument("value", nargs="?", default="now")

    sub = add("filetype", command_filetype, "Classify a file by content and extension.")
    sub.add_argument("path")

    sub = add("storage-order", command_storage_order, "List files in cluster order.")
    sub.add_argument("path")

    add("list-filesystems", command_list_filesystems, "List the filing systems this build recognises.", partition=False)

    sub = add("tosrom", command_tosrom, "Decode a TOS ROM's header, segments and entry points.", partition=False)
    sub.add_argument("--as", dest="output_format", default="text", choices=("text", "json"))
    sub.add_argument("image")

    sub = add("describe-filesystem", command_describe_filesystem, "Describe one filing system.", partition=False)
    sub.add_argument("name")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        from ..version import __version__

        print(__version__)
        return 0
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return handler(args)
    except (ConfigurationError, DataError) as error:
        sys.stderr.write(f"Error: {error}\n")
        if args.debug:
            raise
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
