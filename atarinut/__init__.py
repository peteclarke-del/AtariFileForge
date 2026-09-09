"""Atarinut: the GEMDOS filing-system engine used by Atari File Forge.

Atarinut reads and writes the media an Atari actually used:

* **OFS** and **FFS** volumes (``DOS\\0`` to ``DOS\\5``), on 880 KiB and
  1.76 MiB floppies and on hard-drive partitions of any size.
* **RDB** (Rigid Disk Block) partitioned hard-drive files, so one ``.hdf``
  can present several independently mountable volumes.
* **Kickstart** ROM images, decoded into their resident-module list.

The public API is deliberately small and is the only surface Atari File Forge
depends on:

``atarinut.filesystem``
    ``create_filesystem``, ``reader_for``, ``identify``, ``geometry_from_geo``
    and the ``AtariMetadata`` / ``Datestamped`` / ``Filetyped`` protocols.
``atarinut.disc.mount``
    ``resolve_mount``, which turns ``image.adf:C/List`` into a mounted volume
    and an inner path.
``atarinut.disc.cli``
    The ``adisc`` command line and the bulk-copy helpers it shares with the
    workbench.
``atarinut.file``
    ``Access``, ``AtariMeta`` and the protection-bit helpers.
``atarinut.basic``
    ST BASIC tokenising and detokenising.
``atarinut.kickfs``
    Kickstart ROM identity and module decoding.
"""

from .version import __version__

__all__ = ["__version__"]
