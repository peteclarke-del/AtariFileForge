"""Pure helpers for constructing logical ROM bytes from physical chip files."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path


MAX_COMBINED_ROM_SIZE = 64 * 1024 * 1024
MAX_ROM_COMPONENTS = 256
COPY_BLOCK_SIZE = 1024 * 1024
ROM_COMPONENT_LAYOUTS = {"linear", "byte-interleaved-2", "byte-interleaved-4"}

#: The chip sets a real board takes for each TOS ROM size, as
#: ``(chip count, chip size, byte lanes, label)``. Every ST-family board is a
#: 16-bit bus fed by byte-wide chips, so each set is even/odd pairs.
BOARD_CHIP_SETS = {
    192 * 1024: (
        (6, 32 * 1024, 2, "ST and Mega ST: six 32 KiB chips in three even/odd pairs"),
    ),
    256 * 1024: (
        (2, 128 * 1024, 2, "STE and Mega STE: two 128 KiB chips, even and odd"),
    ),
    512 * 1024: (
        (2, 256 * 1024, 2, "TT and Falcon: two 256 KiB chips, even and odd"),
        (4, 128 * 1024, 2, "TT: four 128 KiB chips in two even/odd pairs"),
    ),
}


def split_into_chips(data: bytes, lanes: int, parts: int) -> list[tuple[str, bytes]]:
    """Split a logical image into the chip files a board takes.

    ``lanes`` byte-interleaves the image (two lanes are the even and odd
    bytes), then each lane is cut into ``parts`` consecutive pieces. The
    names say which socket a piece belongs in: ``even-1`` is the first even
    chip, ``odd-1`` its partner. ``write_combined_rom`` reverses the split:
    concatenate each lane's pieces, then interleave the lanes.
    """
    lanes = int(lanes)
    parts = int(parts)
    if lanes not in {1, 2, 4} or parts < 1:
        raise ValueError("Choose one, two or four byte lanes and at least one chip per lane.")
    if len(data) % (lanes * parts):
        raise ValueError("The image does not divide into that many equal chips.")
    lane_names = {1: ("",), 2: ("even", "odd"), 4: ("lane-1", "lane-2", "lane-3", "lane-4")}[lanes]
    found: list[tuple[str, bytes]] = []
    for index, lane_name in enumerate(lane_names):
        lane = data[index::lanes]
        piece = len(lane) // parts
        for part in range(parts):
            content = lane[part * piece : (part + 1) * piece]
            if parts == 1:
                name = lane_name
            elif lane_name:
                name = f"{lane_name}-{part + 1}"
            else:
                name = f"chip-{part + 1}"
            found.append((name, content))
    return found


def write_combined_rom(
    component_paths: list[Path], output_path: Path, layout: str = "linear"
) -> None:
    components = [Path(path) for path in component_paths]
    if not components:
        raise ValueError("Choose at least one ROM component.")
    if len(components) > MAX_ROM_COMPONENTS:
        raise ValueError(
            f"A ROM set cannot contain more than {MAX_ROM_COMPONENTS} components."
        )
    layout = str(layout or "linear")
    if layout not in ROM_COMPONENT_LAYOUTS:
        raise ValueError("Choose a linear, two-chip or four-chip ROM byte layout.")
    sizes = [path.stat().st_size for path in components]
    if sum(sizes) > MAX_COMBINED_ROM_SIZE:
        raise ValueError("That ROM set is larger than the 64 MiB workbench safety limit.")
    interleaved = layout.startswith("byte-interleaved")
    expected_components = int(layout.rsplit("-", 1)[-1]) if interleaved else None
    if interleaved and len(components) != expected_components:
        raise ValueError(
            f"The {layout} layout requires exactly {expected_components} components."
        )
    if interleaved and len(set(sizes)) != 1:
        raise ValueError("Byte-interleaved ROM components must have exactly equal sizes.")
    output_path = Path(output_path)
    if interleaved:
        with ExitStack() as stack:
            sources = [stack.enter_context(path.open("rb")) for path in components]
            output = stack.enter_context(output_path.open("wb"))
            remaining = sizes[0]
            while remaining:
                amount = min(COPY_BLOCK_SIZE, remaining)
                rows = [source.read(amount) for source in sources]
                if any(len(row) != amount for row in rows):
                    raise ValueError("A ROM component changed while it was being read.")
                combined = bytearray(amount * len(rows))
                for index, row in enumerate(rows):
                    combined[index::len(rows)] = row
                output.write(combined)
                remaining -= amount
        return
    with output_path.open("wb") as output:
        for path, size in zip(components, sizes, strict=True):
            with path.open("rb") as source:
                remaining = size
                while remaining:
                    chunk = source.read(min(COPY_BLOCK_SIZE, remaining))
                    if not chunk:
                        raise ValueError("A ROM component changed while it was being read.")
                    output.write(chunk)
                    remaining -= len(chunk)


__all__ = [
    "BOARD_CHIP_SETS",
    "COPY_BLOCK_SIZE",
    "MAX_COMBINED_ROM_SIZE",
    "MAX_ROM_COMPONENTS",
    "ROM_COMPONENT_LAYOUTS",
    "split_into_chips",
    "write_combined_rom",
]
