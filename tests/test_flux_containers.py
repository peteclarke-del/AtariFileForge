from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.errors import DiskError
from app.flux_containers import (
    BROWSEABLE_KINDS,
    CANONICAL_SIZES,
    FLOPPY_SIZES,
    FLUX_CONTAINERS,
    FLUX_ENCODABLE_SIZES,
    HFE,
    SCP,
    SECTOR_IMAGE_SUFFIX,
    SECTOR_SIZE,
    FluxEngine,
    is_flux_encodable,
    restore_omitted_tail_sector,
    sector_image_suffix,
)
from app.floppy_geometry import GEOMETRIES, canonical_sizes

DS_720K = 737_280
SS_360K = 368_640
DS_800K = 819_200
DS_880K = 901_120
HD_1440K = 1_474_560
PC_180K = 184_320


def _argument(arguments: list[str], prefix: str) -> str | None:
    return next(
        (item.removeprefix(prefix) for item in arguments if item.startswith(prefix)),
        None,
    )


def _write_output(arguments: list[str], content: bytes) -> None:
    output = _argument(arguments, "-foutput:")
    if output:
        Path(output).write_bytes(content)


class SectorGeometryTests(unittest.TestCase):
    def test_the_policy_is_keyed_by_gemdos_and_reads_the_geometry_table(self) -> None:
        self.assertEqual(BROWSEABLE_KINDS, {"gemdos"})
        self.assertEqual(set(CANONICAL_SIZES), {"gemdos"})
        self.assertEqual(CANONICAL_SIZES["gemdos"], canonical_sizes())
        self.assertEqual(FLOPPY_SIZES, canonical_sizes())

    def test_every_floppy_geometry_is_an_st_whatever_its_sides(self) -> None:
        for size in (DS_720K, SS_360K, DS_800K, DS_880K, HD_1440K, PC_180K):
            with self.subTest(size=size):
                self.assertEqual(sector_image_suffix("gemdos", size), ".st")
        self.assertEqual(sector_image_suffix("gemdos", SS_360K, 1), ".st")
        self.assertEqual(sector_image_suffix("gemdos", SS_360K, 2), ".st")
        # A container that claims one side over a size only a double-sided
        # disk has is still a floppy; the claim is for the caller to warn about.
        self.assertEqual(sector_image_suffix("gemdos", DS_720K, 1), ".st")
        self.assertEqual(SECTOR_IMAGE_SUFFIX, ".st")

    def test_anything_larger_than_a_floppy_is_a_hard_disk_image(self) -> None:
        self.assertEqual(sector_image_suffix("gemdos", 20 * 1024 * 1024), ".img")
        self.assertEqual(sector_image_suffix("gemdos", DS_720K + 512), ".img")

    def test_the_st_family_and_high_density_encode_to_flux(self) -> None:
        """HxCFE's ST loader reads the boot sector, so every ST shape encodes.

        No layout name is passed; what decides the question is whether the
        geometry is one the ST loader reads back.
        """
        expected = {
            item.size for item in GEOMETRIES.values() if not item.identifier.startswith("pc-")
        }
        self.assertEqual(FLUX_ENCODABLE_SIZES, expected)
        for size in (DS_720K, SS_360K, DS_800K, DS_880K, HD_1440K, GEOMETRIES["ds-82t-10s"].size):
            with self.subTest(size=size):
                self.assertTrue(is_flux_encodable("gemdos", size))
        self.assertFalse(is_flux_encodable("gemdos", 800 * 1024 + 512))

    def test_the_pc_180k_geometry_has_no_flux_equivalent(self) -> None:
        self.assertFalse(is_flux_encodable("gemdos", PC_180K))

    def test_a_hard_disk_image_is_never_flux_encodable(self) -> None:
        self.assertTrue(is_flux_encodable("gemdos", DS_720K))
        self.assertFalse(is_flux_encodable("gemdos", 20 * 1024 * 1024))
        self.assertFalse(is_flux_encodable("harddisk", DS_720K))


class TailSectorRepairTests(unittest.TestCase):
    """The repair must be usable for its one real case and refuse everything else."""

    def _image(self, folder: str, size: int) -> Path:
        path = Path(folder) / "decoded.img"
        path.write_bytes(b"\xAA" * size)
        return path

    def test_one_short_sector_is_restored_to_the_canonical_size(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = self._image(folder, DS_720K - SECTOR_SIZE)
            self.assertTrue(restore_omitted_tail_sector(image, "gemdos"))
            self.assertEqual(image.stat().st_size, DS_720K)

    def test_the_restored_sector_is_blank_and_existing_bytes_are_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = self._image(folder, SS_360K - SECTOR_SIZE)
            restore_omitted_tail_sector(image, "gemdos")
            data = image.read_bytes()
            self.assertEqual(data[: SS_360K - SECTOR_SIZE], b"\xAA" * (SS_360K - SECTOR_SIZE))
            self.assertEqual(data[SS_360K - SECTOR_SIZE :], bytes(SECTOR_SIZE))

    def test_an_already_complete_image_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = self._image(folder, DS_720K)
            self.assertFalse(restore_omitted_tail_sector(image, "gemdos"))
            self.assertEqual(image.stat().st_size, DS_720K)

    def test_no_canonical_size_is_one_sector_short_of_another(self) -> None:
        """Otherwise a complete image of one shape could be padded into another."""
        for size in FLOPPY_SIZES:
            self.assertNotIn(size + SECTOR_SIZE, FLOPPY_SIZES)

    def test_more_than_one_missing_sector_is_never_padded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = self._image(folder, DS_720K - (SECTOR_SIZE * 2))
            self.assertFalse(restore_omitted_tail_sector(image, "gemdos"))
            self.assertEqual(image.stat().st_size, DS_720K - (SECTOR_SIZE * 2))

    def test_a_size_unrelated_to_any_geometry_is_never_padded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = self._image(folder, 500_000)
            self.assertFalse(restore_omitted_tail_sector(image, "gemdos"))
            self.assertEqual(image.stat().st_size, 500_000)

    def test_a_kind_without_canonical_geometry_is_never_padded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = self._image(folder, DS_720K - SECTOR_SIZE)
            self.assertFalse(restore_omitted_tail_sector(image, "harddisk"))

    def test_expected_size_selects_the_geometry_it_names(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = self._image(folder, SS_360K - SECTOR_SIZE)
            self.assertTrue(
                restore_omitted_tail_sector(image, "gemdos", expected_size=SS_360K)
            )
            self.assertEqual(image.stat().st_size, SS_360K)

    def test_an_implausible_expected_size_is_ignored_not_obeyed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = self._image(folder, HD_1440K - SECTOR_SIZE)
            # 999 is not a canonical geometry, so the repair falls back to the
            # size the file is actually one sector short of.
            self.assertTrue(restore_omitted_tail_sector(image, "gemdos", expected_size=999))
            self.assertEqual(image.stat().st_size, HD_1440K)

    def test_a_missing_file_is_reported_rather_than_created(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            absent = Path(folder) / "never-written.img"
            self.assertFalse(restore_omitted_tail_sector(absent, "gemdos"))
            self.assertFalse(absent.exists())


class FluxContainerRegistryTests(unittest.TestCase):
    def test_both_containers_are_registered_under_their_identifier(self) -> None:
        self.assertEqual(set(FLUX_CONTAINERS), {"hfe", "scp"})
        for identifier, container in FLUX_CONTAINERS.items():
            self.assertEqual(container.identifier, identifier)
            self.assertEqual(container.extension, f".{identifier}")
            self.assertEqual(container.display, identifier.upper())
            self.assertTrue(container.plugin)
            self.assertTrue(container.label)


class FluxEngineTests(unittest.TestCase):
    def test_encode_never_names_a_layout(self) -> None:
        """HxCFE's ST loader settles the geometry from the boot sector.

        It reads the BIOS parameter block, then its own size table, then
        tries every plausible shape, so a layout name is never needed and a
        wrong one makes HxCFE refuse the input outright. The policy is: no
        ``-uselayout``, and the sectors must be a ``.st`` so that loader is
        the one HxCFE picks.
        """
        with tempfile.TemporaryDirectory() as folder:
            sectors = Path(folder) / "disk.st"
            sectors.write_bytes(bytes(DS_720K))
            seen: list[list[str]] = []

            def run(arguments):
                seen.append(arguments)
                _write_output(arguments, b"FLUX")
                return ""

            FluxEngine(run).encode_from_sectors(
                sectors, SCP, Path(folder) / "out.scp", kind="gemdos"
            )
            self.assertFalse([item for item in seen[0] if item.startswith("-uselayout:")])
            self.assertIn("-conv:SCP_FLUX_STREAM", seen[0])
            self.assertEqual(_argument(seen[0], "-finput:"), str(sectors))

    def test_encode_refuses_sectors_that_are_not_named_as_an_st(self) -> None:
        """HxCFE picks its loader by suffix; a ``.img`` would go to the raw loader."""
        with tempfile.TemporaryDirectory() as folder:
            sectors = Path(folder) / "disk.img"
            sectors.write_bytes(bytes(DS_720K))

            def run(arguments):
                raise AssertionError("HxCFE must not be invoked for a misnamed image")

            with self.assertRaisesRegex(DiskError, "ST loader"):
                FluxEngine(run).encode_from_sectors(
                    sectors, HFE, Path(folder) / "out.hfe", kind="gemdos"
                )

    def test_encode_refuses_a_geometry_hxcfe_cannot_write(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            pc = Path(folder) / "disk.st"
            pc.write_bytes(bytes(PC_180K))

            def run(arguments):
                raise AssertionError("HxCFE must not be invoked for this geometry")

            with self.assertRaisesRegex(DiskError, "no flux equivalent"):
                FluxEngine(run).encode_from_sectors(
                    pc, HFE, Path(folder) / "out.hfe", kind="gemdos"
                )

    def test_encode_passes_the_reference_container_only_when_given(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            sectors = Path(folder) / "disk.st"
            sectors.write_bytes(bytes(DS_720K))
            original = Path(folder) / "capture.scp"
            original.write_bytes(b"SCP")
            seen: list[list[str]] = []

            def run(arguments):
                seen.append(arguments)
                _write_output(arguments, b"FLUX")
                return ""

            engine = FluxEngine(run)
            engine.encode_from_sectors(
                sectors, SCP, Path(folder) / "a.scp", kind="gemdos", reference=original
            )
            self.assertEqual(_argument(seen[0], "-reffile:"), str(original))

            seen.clear()
            engine.encode_from_sectors(sectors, SCP, Path(folder) / "b.scp", kind="gemdos")
            self.assertIsNone(_argument(seen[0], "-reffile:"))

    def test_round_trip_check_tolerates_one_omitted_tail_sector(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            sectors = Path(folder) / "disk.st"
            sectors.write_bytes(bytes(DS_720K))
            container = Path(folder) / "disk.scp"
            container.write_bytes(b"SCP")

            def run(arguments):
                _write_output(arguments, bytes(DS_720K - SECTOR_SIZE))
                return ""

            self.assertTrue(FluxEngine(run).decodes_back_to(container, sectors, "gemdos"))

    def test_round_trip_check_rejects_genuinely_different_sectors(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            sectors = Path(folder) / "disk.st"
            sectors.write_bytes(b"\x01" * SS_360K)
            container = Path(folder) / "disk.hfe"
            container.write_bytes(b"HXC")

            def run(arguments):
                _write_output(arguments, b"\x02" * SS_360K)
                return ""

            self.assertFalse(FluxEngine(run).decodes_back_to(container, sectors, "gemdos"))

    def test_round_trip_check_treats_an_engine_failure_as_no_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            sectors = Path(folder) / "disk.st"
            sectors.write_bytes(bytes(SS_360K))
            container = Path(folder) / "disk.hfe"
            container.write_bytes(b"HXC")

            def run(_arguments):
                raise DiskError("HxCFE failed")

            self.assertFalse(FluxEngine(run).decodes_back_to(container, sectors, "gemdos"))

    def test_round_trip_check_removes_its_temporary_decode(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            sectors = Path(folder) / "disk.st"
            sectors.write_bytes(bytes(SS_360K))
            container = Path(folder) / "disk.hfe"
            container.write_bytes(b"HXC")

            def run(arguments):
                _write_output(arguments, bytes(SS_360K))
                return ""

            FluxEngine(run).decodes_back_to(container, sectors, "gemdos")
            self.assertEqual(list(Path(folder).glob("*-verify.img")), [])

    def test_encode_and_verify_returns_a_container_that_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            sectors = Path(folder) / "disk.st"
            sectors.write_bytes(bytes(DS_720K))
            output = Path(folder) / "out.scp"

            def run(arguments):
                if any(item.startswith("-conv:SCP_FLUX_STREAM") for item in arguments):
                    _write_output(arguments, b"SCP-FLUX")
                else:
                    _write_output(arguments, bytes(DS_720K))
                return ""

            result = FluxEngine(run).encode_and_verify(
                sectors, SCP, output, kind="gemdos", failure_message="nope"
            )
            self.assertEqual(result, output)
            self.assertEqual(output.read_bytes(), b"SCP-FLUX")

    def test_encode_and_verify_discards_a_container_that_does_not_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            sectors = Path(folder) / "disk.st"
            sectors.write_bytes(bytes(DS_720K))
            output = Path(folder) / "out.scp"

            def run(arguments):
                if any(item.startswith("-conv:SCP_FLUX_STREAM") for item in arguments):
                    _write_output(arguments, b"SCP-FLUX")
                else:
                    _write_output(arguments, bytes(1))
                return ""

            with self.assertRaisesRegex(DiskError, "sectors did not match"):
                FluxEngine(run).encode_and_verify(
                    sectors,
                    SCP,
                    output,
                    kind="gemdos",
                    failure_message="The sectors did not match.",
                )
            self.assertFalse(
                output.exists(),
                "an unverified flux image must not be left on disk",
            )

    def test_encode_and_verify_rejects_an_empty_engine_result(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            sectors = Path(folder) / "disk.st"
            sectors.write_bytes(bytes(DS_720K))

            def run(_arguments):
                return ""

            with self.assertRaisesRegex(DiskError, "did not produce a usable SCP"):
                FluxEngine(run).encode_and_verify(
                    sectors,
                    SCP,
                    Path(folder) / "out.scp",
                    kind="gemdos",
                    failure_message="unused",
                )


if __name__ == "__main__":
    unittest.main()
