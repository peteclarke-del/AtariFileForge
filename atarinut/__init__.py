"""Atarinut: the GEMDOS filing-system engine used by Atari File Forge.

Atarinut reads and writes the media an Atari ST actually used:

* **FAT12** floppies in every format TOS writes, from single-sided 360 KiB
  to high-density 1.44 MiB, and **FAT16** hard-disk volumes with the large
  logical sectors AHDI, HDX and HDDRIVER choose.
* **AHDI** partitioned hard-disk images, including XGM chains, ICD tables,
  PC-style MBR tables and byte-swapped IDE dumps.
* **TOS ROM** images, decoded into their components by ``atarinut.tosrom``.

The public API is deliberately small and is the only surface Atari File Forge
depends on:

``atarinut.filesystem``
    ``create_filesystem``, ``reader_for``, ``identify``, ``format_volume``,
    ``geometry_from_bpb``, ``create_partitioned_image`` and the
    ``AtariMetadata`` / ``Datestamped`` protocols.
``atarinut.disc.mount``
    ``resolve_mount``, which turns ``image.st:AUTO\\FOO.PRG`` into a mounted
    volume and an inner path, with ``partition=N`` for hard disks.
``atarinut.disc.cli``
    The ``python -m atarinut`` command line and the bulk-copy helpers it
    shares with the workbench.
``atarinut.file``
    ``Access``, ``AtariMeta`` and the attribute and datestamp helpers.
``atarinut.basic``
    ST BASIC tokenising and detokenising.
"""

from .version import __version__

__all__ = ["__version__"]
