"""The ``python -m atarinut`` command line: verbs, JSON shapes and mounts."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from atarinut.disc import cli
from atarinut.disc.mount import resolve_mount, split_compound
from atarinut.filesystem.blocks import SECTOR_SIZE, is_executable_sector

MIB = 1024 * 1024


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def run_json(*argv: str) -> dict:
    code, out, err = run(*argv)
    assert code == 0, err
    return json.loads(out)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.image = self.tmp / "disk.st"
        code, _out, err = run("create", "--format", "ds-720k", "--label", "GAMES", str(self.image))
        self.assertEqual(code, 0, err)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def compound(self, inner: str = "") -> str:
        return f"{self.image}:{inner}"

    def test_create_and_identify(self) -> None:
        self.assertEqual(self.image.stat().st_size, 1440 * SECTOR_SIZE)
        report = run_json("identify", "--as", "json", str(self.image))
        rows = report["reports"]["candidates"]["rows"]
        self.assertEqual(rows[0]["filesystem"], "gemdos")
        self.assertEqual(rows[0]["confidence"], 1.0)
        self.assertIn("FAT12", rows[0]["detail"])
        code, out, _err = run("identify", str(self.image))
        self.assertEqual(code, 0)
        self.assertIn("gemdos", out)
        for name, size in (("ss-360k", 720), ("hd-1440k", 2880), ("880k", 1760)):
            path = self.tmp / f"{name}.st"
            self.assertEqual(run("create", "--format", name, str(path))[0], 0)
            self.assertEqual(path.stat().st_size, size * SECTOR_SIZE)
        code, _out, err = run("create", "--format", "nonsense", str(self.tmp / "x.st"))
        self.assertEqual(code, 1)
        self.assertIn("floppy format", err)

    def test_put_get_cat_type_and_ls_json_shape(self) -> None:
        source = self.tmp / "hello.txt"
        source.write_bytes(b"hello\r\nworld\r\n")
        self.assertEqual(run("put", str(source), self.compound("AUTO\\HELLO.TXT"))[0], 0)
        self.assertEqual(run("put", "--attributes", "r", str(source), self.compound("LOCKED.TXT"))[0], 0)
        report = run_json("ls", "--as", "json", self.compound())
        entries = report["reports"]["entries"]
        self.assertEqual(entries["metadata"]["title"], "GAMES")
        self.assertEqual(entries["metadata"]["format"], "FAT12")
        self.assertEqual(entries["metadata"]["path"], "")
        rows = {row["name"]: row for row in entries["rows"]}
        self.assertEqual(set(rows), {"AUTO", "LOCKED.TXT"})
        self.assertEqual(rows["AUTO"]["type"], "dir")
        self.assertEqual(rows["AUTO"]["length"], 1)
        self.assertEqual(rows["AUTO"]["attr"], "----d-")
        locked = rows["LOCKED.TXT"]
        self.assertEqual(locked["type"], "file")
        self.assertEqual(locked["length"], 14)
        self.assertEqual(locked["attr"], "r----a")
        self.assertEqual(locked["attributes"], 0x21)
        self.assertEqual(locked["load"], 0x21)
        self.assertEqual(locked["exec"], 0)
        self.assertEqual(locked["filetype"], "text")
        self.assertRegex(locked["datestamp"], r"^\d{4}-\d{2}-\d{2}T")
        for key in ("name", "type", "load", "exec", "filetype", "datestamp", "length", "attr"):
            self.assertIn(key, locked)
        nested = run_json("ls", "--as", "json", self.compound("AUTO"))
        self.assertEqual([row["name"] for row in nested["reports"]["entries"]["rows"]], ["HELLO.TXT"])
        self.assertEqual(nested["reports"]["entries"]["metadata"]["path"], "AUTO")

        target = self.tmp / "out.txt"
        self.assertEqual(run("get", "--meta-format", "none", self.compound("auto/hello.txt"), str(target))[0], 0)
        self.assertEqual(target.read_bytes(), source.read_bytes())
        code, out, _err = run("type", self.compound("AUTO\\HELLO.TXT"))
        self.assertEqual(code, 0)
        self.assertEqual(out, "hello\nworld\n")
        code, out, _err = run("ls", self.compound())
        self.assertEqual(code, 0)
        self.assertIn("LOCKED.TXT", out)
        self.assertIn("<DIR>", out)

    def test_stat_validate_title_opt_and_freemap(self) -> None:
        report = run_json("stat", "--as", "json", self.compound())
        row = report["reports"]["volume"]["rows"][0]
        self.assertEqual(row["name"], "GAMES")
        self.assertEqual(row["format"], "FAT12")
        self.assertEqual(row["size"], 711 * 1024)
        self.assertEqual(row["free"], 711 * 1024)
        self.assertFalse(row["bootable"])
        self.assertEqual(row["geometry"]["sectorsPerTrack"], 9)
        self.assertEqual(run("mkdir", self.compound("A\\B"))[0], 0)
        entry = run_json("stat", "--as", "json", self.compound("A\\B"))["reports"]["entry"]["rows"][0]
        self.assertEqual((entry["name"], entry["type"], entry["length"], entry["blocks"]), ("B", "dir", 0, 1))
        self.assertEqual(entry["attr"], "----d-")
        code, out, _err = run("validate", str(self.image))
        self.assertEqual(code, 0)
        self.assertIn("No structural errors", out)
        code, out, _err = run("title", self.compound())
        self.assertEqual(out.strip(), "GAMES")
        self.assertEqual(run("title", self.compound(), "WORK")[0], 0)
        self.assertEqual(run("title", self.compound())[1].strip(), "WORK")
        code, _out, err = run("title", self.compound("A"), "X")
        self.assertEqual(code, 1)
        self.assertIn("label", err)
        self.assertEqual(run("opt", str(self.image))[1].strip(), "0")
        self.assertEqual(run("opt", str(self.image), "1")[0], 0)
        self.assertEqual(run("opt", str(self.image))[1].strip(), "1")
        self.assertTrue(is_executable_sector(self.image.read_bytes()[:512]))
        self.assertEqual(run("opt", str(self.image), "0")[0], 0)
        self.assertEqual(run("opt", str(self.image))[1].strip(), "0")
        code, out, _err = run("freemap", str(self.image))
        self.assertEqual(code, 0)
        self.assertIn("709 free of 711 clusters", out)

    def test_mv_rm_chmod_lock_unlock_and_datestamps(self) -> None:
        source = self.tmp / "f.bin"
        source.write_bytes(b"\x60\x1a" + bytes(40))
        run("put", str(source), self.compound("ONE.PRG"))
        self.assertEqual(run("mv", self.compound("ONE.PRG"), "TWO.PRG")[0], 0)
        self.assertEqual(run("mkdir", self.compound("DIR"))[0], 0)
        self.assertEqual(run("mv", self.compound("TWO.PRG"), "DIR\\TWO.PRG")[0], 0)
        code, out, _err = run("tree", self.compound())
        self.assertEqual(out.splitlines(), ["DIR\\", "  TWO.PRG"])
        code, out, _err = run("find", self.compound(), "*.prg")
        self.assertEqual(out.strip(), "DIR\\TWO.PRG")
        code, out, _err = run("filetype", self.compound("DIR\\TWO.PRG"))
        self.assertEqual(out.strip(), "Program")
        self.assertEqual(run("chmod", self.compound("DIR\\TWO.PRG"), "rh---a")[0], 0)
        rows = run_json("ls", "--as", "json", self.compound("DIR"))["reports"]["entries"]["rows"]
        self.assertEqual(rows[0]["attr"], "rh---a")
        code, _out, err = run("rm", self.compound("DIR\\TWO.PRG"))
        self.assertEqual(code, 1)
        self.assertIn("read-only", err)
        self.assertEqual(run("unlock", self.compound("DIR\\TWO.PRG"))[0], 0)
        rows = run_json("ls", "--as", "json", self.compound("DIR"))["reports"]["entries"]["rows"]
        self.assertEqual(rows[0]["attr"], "-h---a")
        self.assertEqual(run("lock", self.compound("DIR\\TWO.PRG"))[0], 0)
        self.assertEqual(run("set-datestamp", self.compound("DIR\\TWO.PRG"), "1991-03-04T05:06:07+00:00")[0], 0)
        self.assertEqual(run("get-datestamp", self.compound("DIR\\TWO.PRG"))[1].strip(), "1991-03-04T05:06:06.000+00:00")
        self.assertEqual(run("rm", "--force", "--recursive", self.compound("DIR"))[0], 0)
        self.assertEqual(run_json("ls", "--as", "json", self.compound())["reports"]["entries"]["rows"], [])
        self.assertEqual(run("validate", str(self.image))[0], 0)

    def test_import_export_cp_and_compact(self) -> None:
        tree = self.tmp / "tree"
        (tree / "AUTO").mkdir(parents=True)
        (tree / "AUTO" / "BOOT.PRG").write_bytes(b"\x60\x1a" + bytes(2000))
        (tree / "README.TXT").write_bytes(b"read me")
        self.assertEqual(run("import", str(tree), self.compound())[0], 0)
        exported = self.tmp / "exported"
        self.assertEqual(run("export", self.compound(), str(exported))[0], 0)
        self.assertEqual((exported / "AUTO" / "BOOT.PRG").read_bytes(), b"\x60\x1a" + bytes(2000))
        self.assertEqual((exported / "README.TXT").read_bytes(), b"read me")

        other = self.tmp / "other.st"
        run("create", "--format", "ss-360k", "--label", "COPY", str(other))
        self.assertEqual(run("cp", "--recursive", self.compound("AUTO"), f"{other}:")[0], 0)
        self.assertEqual(run("cp", self.compound("README.TXT"), f"{other}:DOCS\\README.TXT")[0], 0)
        rows = run_json("ls", "--as", "json", f"{other}:")["reports"]["entries"]["rows"]
        self.assertEqual([row["name"] for row in rows], ["AUTO", "DOCS"])
        with resolve_mount(f"{other}:AUTO\\BOOT.PRG") as resolved:
            self.assertEqual(resolved.mount.read_bytes(resolved.path), b"\x60\x1a" + bytes(2000))
            self.assertEqual(resolved.path, "AUTO\\BOOT.PRG")
        code, _out, err = run("cp", self.compound("README.TXT"), f"{other}:DOCS\\README.TXT")
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertEqual(run("cp", "--force", self.compound("README.TXT"), f"{other}:DOCS\\README.TXT")[0], 0)
        code, out, _err = run("compact", str(other))
        self.assertEqual(code, 0)
        self.assertIn("cluster(s) moved", out)
        self.assertEqual(run("validate", str(other))[0], 0)
        code, out, _err = run("storage-order", f"{other}:")
        self.assertEqual(code, 0)
        self.assertIn("AUTO\\BOOT.PRG", out)

    def test_format_in_place(self) -> None:
        code, out, _err = run("format", "--label", "FRESH", str(self.image))
        self.assertEqual(code, 0)
        self.assertIn("FAT12", out)
        self.assertEqual(run("title", self.compound())[1].strip(), "FRESH")

    def test_errors_are_reported_on_stderr(self) -> None:
        code, _out, err = run("ls", self.compound("MISSING"))
        self.assertEqual(code, 1)
        self.assertIn("Path not found", err)
        code, _out, err = run("cat", str(self.tmp / "absent.st") + ":X")
        self.assertEqual(code, 1)
        code, _out, err = run("mkdir", self.compound("BAD NAME"))
        self.assertEqual(code, 1)
        self.assertIn("space", err)

    def test_list_and_describe_filesystems(self) -> None:
        code, out, _err = run("list-filesystems")
        self.assertEqual(code, 0)
        for name in ("gemdos", "fat12", "fat16", "ahdi", "tosrom"):
            self.assertIn(name, out)
        code, out, _err = run("describe-filesystem", "gemdos")
        self.assertIn("ds-720k", out)

    def test_module_entry_point(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "atarinut", "--version"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip())


class HardDiskCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.image = self.tmp / "drive.ahd"
        code, _out, err = run(
            "create", "--filesystem", "ahdi", "--size", "20M", "--partitions", "2", "--label", "HD",
            "--bootable", str(self.image),
        )
        self.assertEqual(code, 0, err)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_partitions_report(self) -> None:
        self.assertEqual(self.image.stat().st_size, 20 * MIB)
        report = run_json("partitions", "--as", "json", str(self.image))["reports"]["partitions"]
        self.assertEqual(report["metadata"]["scheme"], "ahdi")
        # ``--bootable`` flags the first partition, which is what tells a
        # driver where to start. The root sector stays inert because nothing
        # has written a loader into it; see RootSectorTests for why.
        self.assertFalse(report["metadata"]["bootable"])
        self.assertTrue(report["rows"][0]["bootable"])
        rows = report["rows"]
        self.assertEqual([row["name"] for row in rows], ["C:", "D:"])
        self.assertEqual([row["label"] for row in rows], ["HD1", "HD2"])
        self.assertEqual(rows[0]["id"], "GEM")
        self.assertEqual(rows[0]["format"], "FAT16")
        self.assertTrue(rows[0]["bootable"])
        self.assertFalse(rows[1]["bootable"])
        self.assertEqual(rows[0]["startSector"], 1)
        self.assertGreater(rows[0]["free"], 0)
        self.assertEqual(rows[0]["type"], "dir")
        identified = run_json("identify", "--as", "json", str(self.image))["reports"]["candidates"]["rows"]
        self.assertEqual(identified[0]["filesystem"], "ahdi")
        code, out, _err = run("partitions", str(self.image))
        self.assertEqual(code, 0)
        self.assertIn("2 AHDI partitions", out)
        listing = run_json("ls", "--as", "json", f"{self.image}:")["reports"]["entries"]
        self.assertEqual(len(listing["rows"]), 2)
        stat = run_json("stat", "--as", "json", f"{self.image}:")
        self.assertIn("partitions", stat["reports"])

    def test_partition_selection(self) -> None:
        source = self.tmp / "a.txt"
        source.write_bytes(b"partition two")
        self.assertEqual(run("put", "--partition", "1", str(source), f"{self.image}:AUTO\\A.TXT")[0], 0)
        self.assertEqual(run("mkdir", "--partition", "0", f"{self.image}:FIRST")[0], 0)
        rows = run_json("ls", "--partition", "1", "--as", "json", f"{self.image}:")["reports"]["entries"]
        self.assertEqual(rows["metadata"]["title"], "HD2")
        self.assertEqual([row["name"] for row in rows["rows"]], ["AUTO"])
        rows = run_json("ls", "--partition", "0", "--as", "json", f"{self.image}:")["reports"]["entries"]
        self.assertEqual([row["name"] for row in rows["rows"]], ["FIRST"])
        fetched = self.tmp / "fetched.txt"
        code, _out, err = run("get", "--partition", "1", f"{self.image}:AUTO\\A.TXT", str(fetched))
        self.assertEqual(code, 0, err)
        self.assertEqual(fetched.read_bytes(), b"partition two")
        self.assertEqual(run("validate", str(self.image))[0], 0)
        with resolve_mount(f"{self.image}:AUTO\\A.TXT", partition=1) as resolved:
            self.assertEqual(resolved.mount.read_bytes(resolved.path), b"partition two")
            self.assertEqual(resolved.partition, 1)
        code, _out, err = run("ls", "--partition", "5", f"{self.image}:")
        self.assertEqual(code, 1)
        self.assertIn("Partition 5", err)
        self.assertEqual(run("format", "--partition", "1", "--label", "WIPED", str(self.image))[0], 0)
        rows = run_json("ls", "--partition", "1", "--as", "json", f"{self.image}:")["reports"]["entries"]
        self.assertEqual(rows["rows"], [])
        self.assertEqual(rows["metadata"]["title"], "WIPED")

    def test_bare_hard_disk_volume(self) -> None:
        bare = self.tmp / "bare.img"
        code, _out, err = run("create", "--size", "24M", "--label", "BARE", str(bare))
        self.assertEqual(code, 0, err)
        self.assertIn("TOS 1.00", err)
        report = run_json("stat", "--as", "json", f"{bare}:")["reports"]["volume"]["rows"][0]
        self.assertEqual(report["format"], "FAT16")
        self.assertEqual(report["name"], "BARE")
        self.assertEqual(report["geometry"]["sectorSize"], 512)
        code, _out, err = run("partitions", str(bare))
        self.assertEqual(code, 1)
        self.assertIn("bare volume", err)


class CompoundPathTests(unittest.TestCase):
    def test_split_compound_prefers_the_longest_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "a:b.st"
            run("create", str(image))
            self.assertEqual(split_compound(f"{image}:AUTO\\X"), (image, "AUTO\\X"))
            self.assertEqual(split_compound(str(image)), (image, ""))
            self.assertEqual(split_compound(f"{image}:"), (image, ""))


if __name__ == "__main__":
    unittest.main()
