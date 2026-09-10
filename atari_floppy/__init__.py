"""Reusable, UI-neutral floppy-controller support for Atari media."""

from .device import (
    ATARI_GEOMETRIES,
    DEVICE_SUFFIXES,
    KNOWN_DEVICES,
    FloppyDevice,
    FloppyError,
    FloppyGeometry,
    FloppyProbe,
    FloppyReadResult,
    FloppyWriteResult,
    available_devices,
    device_suffix,
    geometry,
    geometry_for_size,
    image_geometry,
    validated_device,
)

__all__ = [
    "ATARI_GEOMETRIES",
    "DEVICE_SUFFIXES",
    "KNOWN_DEVICES",
    "FloppyDevice",
    "FloppyError",
    "FloppyGeometry",
    "FloppyProbe",
    "FloppyReadResult",
    "FloppyWriteResult",
    "available_devices",
    "device_suffix",
    "geometry",
    "geometry_for_size",
    "image_geometry",
    "validated_device",
]
