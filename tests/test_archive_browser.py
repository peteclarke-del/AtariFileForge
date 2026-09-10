"""Browsing the containers Atari material actually arrives in.

ZIP and LZH are the two the ST scene settled on, so both are covered here
against archives the tests build themselves. LZH is read and never written,
which is a property worth asserting rather than assuming: a rebuild that
quietly re-stored every member would produce a different archive from the one
that went in.
"""

import gzip
import io
import tarfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.archive_browser import (
    ArchiveError,
    MAX_ENTRIES,
    archive_member_editable,
    list_archive,
    preview_archive_member_replacement,
    read_archive_member_details,
    replace_archive_member,
)
from app.atari_metadata import ZIP_HOST_ATARI, ZIP_HOST_DOS
from tests.lha_fixture import archive as lha_archive
from tests.lha_fixture import level1_member, level2_member

try:
    from flask import Flask, jsonify
    from app.disk_service import DiskError
    from app.operations import OperationRegistry
    from app.routes.files import create_files_blueprint
    from app.routes.hex_editor import create_hex_editor_blueprint
    from app.routes.tools import create_tools_blueprint
except ModuleNotFoundError:  # Flask is installed in the production image.
    Flask = None


#: A desktop configuration file, recognised by its own records rather than by
#: its name. Three record letters is enough for the classifier and short
#: enough to read in a failure message.
DESKTOP_INF = b"#a000000\r\n#b000000\r\n#E9A03\r\n"

#: A GEMDOS program header: the 0x601A branch TOS reads, and enough bytes
#: after it for the header to be complete.
GEMDOS_PROGRAM = b"\x60\x1a" + bytes(26) + b"relocated code"

#: ``jmp $8000`` followed by ``rts``. Real 68000 instructions, so the
#: disassembly and cheat-candidate routes have something they can decode, and
#: with enough bytes outside the printable range that the editor does not read
#: the member as text.
M68K_CODE = bytes.fromhex("4EF9000080004E75")


def read_archive_member(data: bytes, filename: str, member_name: str) -> bytes:
    """Read one member's bytes, discarding the metadata the tests do not assert."""
    return read_archive_member_details(data, filename, member_name)[0]


def zip_entry(name: str, host: int, attributes: int) -> zipfile.ZipInfo:
    """Describe one ZIP entry as the archiver on that host system wrote it.

    The attribute byte lives in the low eight bits of the external attributes,
    which is where a TOS archiver puts it and where an MS-DOS one puts the
    identical byte. The date is fixed so the archives are reproducible.
    """
    info = zipfile.ZipInfo(name, (1990, 1, 1, 0, 0, 0))
    info.create_system = host
    info.external_attr = attributes
    return info


def atari_zip(*entries: tuple[zipfile.ZipInfo, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for info, payload in entries:
            archive.writestr(info, payload)
    return stream.getvalue()


class ArchiveBrowserTests(unittest.TestCase):
    def test_zip_is_presented_as_a_safe_hierarchy(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("GAMES/AUTO/DESKTOP.INF", DESKTOP_INF)
            archive.writestr("GAMES/README.TXT", b"Games collection")
        root = list_archive(stream.getvalue(), "GAMES.ZIP")
        self.assertEqual(root["entries"], [{
            "name": "GAMES", "type": "dir", "length": 0,
            "attr": "RO", "archiveEntry": True,
        }])
        games = list_archive(stream.getvalue(), "GAMES.ZIP", "GAMES")
        self.assertEqual([row["name"] for row in games["entries"]], ["AUTO", "README.TXT"])
        self.assertEqual(games["entries"][1]["contentKind"], "text")
        boot = list_archive(stream.getvalue(), "GAMES.ZIP", "GAMES/AUTO")
        self.assertEqual(boot["entries"][0]["contentKind"], "script")
        self.assertEqual(
            read_archive_member(stream.getvalue(), "GAMES.ZIP", "GAMES/README.TXT"),
            b"Games collection",
        )

    def test_an_atari_written_zip_entry_carries_its_attribute_byte_into_the_listing(self):
        """The attribute byte is the whole of the metadata, and it is the entry's own.

        There is no sidecar to read: an archive written under TOS records host
        system 5 and keeps the six GEMDOS bits in its external attributes, so
        the listing row can report them without opening anything else.
        """
        data = atari_zip(
            (zip_entry("GAMES/LOADER.PRG", ZIP_HOST_ATARI, 0x21), GEMDOS_PROGRAM),
            (zip_entry("GAMES/README.TXT", ZIP_HOST_ATARI, 0x20), b"Games collection"),
        )
        listing = list_archive(data, "GAMES.ZIP", "GAMES")
        loader = next(row for row in listing["entries"] if row["name"] == "LOADER.PRG")
        # Bit 0 is read-only and bit 5 is the archive bit, so a locked file
        # written since the last backup prints as r----a.
        self.assertEqual(loader["attributes"], "r----a")
        self.assertEqual(loader["attr"], "r----a")
        self.assertEqual(loader["access"], 0x21)
        self.assertEqual(loader["contentKind"], "program")
        readme = next(row for row in listing["entries"] if row["name"] == "README.TXT")
        self.assertEqual(readme["attributes"], "-----a")
        self.assertEqual(readme["attr"], "-----a")

    def test_a_member_reports_the_attribute_byte_its_own_entry_records(self):
        """Both hosts that record the byte are read, and no other host is guessed at."""
        for host in (ZIP_HOST_ATARI, ZIP_HOST_DOS):
            with self.subTest(host=host):
                data = atari_zip((zip_entry("LOADER.PRG", host, 0x05), GEMDOS_PROGRAM))
                _content, metadata = read_archive_member_details(data, "GAMES.ZIP", "LOADER.PRG")
                self.assertTrue(metadata["metadataAvailable"])
                self.assertEqual(metadata["access"], 0x05)
                self.assertEqual(metadata["attributes"], "r-s---")
                self.assertEqual(metadata["attr"], "r-s---")
        # Host system 3 is Unix. That archiver stores permission bits rather
        # than a GEMDOS attribute byte, so there is nothing here to report and
        # nothing is invented in its place.
        foreign = atari_zip((zip_entry("LOADER.PRG", 3, 0o100644 << 16), GEMDOS_PROGRAM))
        _content, metadata = read_archive_member_details(foreign, "GAMES.ZIP", "LOADER.PRG")
        self.assertFalse(metadata["metadataAvailable"])
        self.assertEqual(metadata["access"], 0)

    def test_tar_and_standalone_gzip_are_supported(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            info = tarfile.TarInfo("DOCS/MANUAL.TXT")
            info.size = 6
            archive.addfile(info, io.BytesIO(b"Manual"))
        self.assertEqual(
            read_archive_member(stream.getvalue(), "DOCS.TAR", "DOCS/MANUAL.TXT"), b"Manual"
        )
        compressed = gzip.compress(b"10 PRINT \"HELLO\"\r")
        listing = list_archive(compressed, "HELLO.BAS.gz")
        self.assertEqual(listing["entries"][0]["name"], "HELLO.BAS")
        self.assertEqual(
            read_archive_member(compressed, "HELLO.BAS.gz", "HELLO.BAS"), b"10 PRINT \"HELLO\"\r"
        )

    def test_editable_archives_are_rebuilt_with_only_the_selected_member_changed(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.comment = b"kept"
            archive.writestr("DOCS/README.TXT", b"Old")
            archive.writestr("DOCS/OTHER.TXT", b"Untouched")
        rebuilt = replace_archive_member(stream.getvalue(), "DOCS.ZIP", "DOCS/README.TXT", b"New text")
        self.assertTrue(archive_member_editable(rebuilt, "DOCS.ZIP"))
        with zipfile.ZipFile(io.BytesIO(rebuilt)) as archive:
            self.assertEqual(archive.comment, b"kept")
            self.assertEqual(archive.read("DOCS/README.TXT"), b"New text")
            self.assertEqual(archive.read("DOCS/OTHER.TXT"), b"Untouched")

        compressed = gzip.compress(b"Before")
        rebuilt = replace_archive_member(compressed, "README.gz", "README", b"After")
        self.assertEqual(gzip.decompress(rebuilt), b"After")

    def test_an_atari_written_zip_keeps_its_attribute_byte_through_a_rebuild(self):
        data = atari_zip(
            (zip_entry("DOCS/README.TXT", ZIP_HOST_ATARI, 0x21), b"Old"),
            (zip_entry("DOCS/OTHER.TXT", ZIP_HOST_ATARI, 0x20), b"Untouched"),
        )
        rebuilt = replace_archive_member(data, "DOCS.ZIP", "DOCS/README.TXT", b"New text")
        listing = list_archive(rebuilt, "DOCS.ZIP", "DOCS")
        self.assertEqual(
            {row["name"]: row["attributes"] for row in listing["entries"]},
            {"README.TXT": "r----a", "OTHER.TXT": "-----a"},
        )
        self.assertEqual(read_archive_member(rebuilt, "DOCS.ZIP", "DOCS/README.TXT"), b"New text")

    def test_an_lzh_member_is_read_but_never_rebuilt(self):
        """This build decodes LZH and does not encode it, so a rebuild is refused.

        Storing the members uncompressed instead would hand back an archive
        that is not the one that went in, and the difference would only show
        up on the machine the file was meant for.
        """
        blob = lha_archive(
            level1_member("AUTO/LOADER.PRG", GEMDOS_PROGRAM, "-lh5-"),
            level2_member("DESKTOP.INF", DESKTOP_INF * 8, "-lh0-"),
        )
        self.assertFalse(archive_member_editable(blob, "GAME.LZH", "DESKTOP.INF"))
        with self.assertRaisesRegex(ArchiveError, "cannot be rebuilt safely"):
            replace_archive_member(blob, "GAME.LZH", "DESKTOP.INF", b"#a000000\r\n")
        preview = preview_archive_member_replacement(
            blob, "GAME.LZH", "DESKTOP.INF", b"#a000000\r\n"
        )
        self.assertEqual(preview["archiveKind"], "lha")
        self.assertEqual(preview["member"], "DESKTOP.INF")
        # Every container this build does rebuild stores its members
        # independently, so no structural proof is asked for before a write.
        self.assertFalse(preview["structuralProofRequired"])

    def test_a_compressed_tar_rebuild_remains_compressed_and_readable(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, payload in (("DOCS/README.TXT", b"Old"), ("DOCS/OTHER.TXT", b"Untouched")):
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
        rebuilt = replace_archive_member(
            stream.getvalue(), "DOCS.TAR.GZ", "DOCS/README.TXT", b"New text"
        )
        self.assertTrue(rebuilt.startswith(b"\x1f\x8b"))
        self.assertEqual(read_archive_member(rebuilt, "DOCS.TAR.GZ", "DOCS/README.TXT"), b"New text")
        self.assertEqual(
            read_archive_member(rebuilt, "DOCS.TAR.GZ", "DOCS/OTHER.TXT"), b"Untouched"
        )

    def test_an_lzh_listing_names_the_method_each_member_was_packed_with(self):
        blob = lha_archive(
            level1_member("AUTO/LOADER.PRG", GEMDOS_PROGRAM, "-lh5-"),
            level2_member("DESKTOP.INF", DESKTOP_INF * 8, "-lh0-"),
        )
        root = list_archive(blob, "GAME.LZH")
        desktop = next(row for row in root["entries"] if row["name"] == "DESKTOP.INF")
        self.assertEqual(desktop["method"], "-lh0-")
        self.assertEqual(desktop["contentKind"], "script")
        loader = list_archive(blob, "GAME.LZH", "AUTO")["entries"][0]
        self.assertEqual(loader["method"], "-lh5-")
        self.assertEqual(loader["contentKind"], "program")

    def test_unsafe_parent_members_are_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("../escape", b"bad")
        with self.assertRaises(ArchiveError):
            list_archive(stream.getvalue(), "UNSAFE.ZIP")

    def test_oversized_archive_inventory_is_rejected_before_member_reads(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for index in range(MAX_ENTRIES + 1):
                archive.writestr(f"empty-{index}", b"")
        with self.assertRaisesRegex(ArchiveError, "more than"):
            list_archive(stream.getvalue(), "TOOMANY.ZIP")

    def test_lzh_archives_are_browsable_containers(self):
        blob = lha_archive(
            level1_member("AUTO/LOADER.PRG", GEMDOS_PROGRAM, "-lh5-"),
            level2_member("DESKTOP.INF", DESKTOP_INF * 8, "-lh0-"),
        )
        listing = list_archive(blob, "GAME.LZH")
        self.assertEqual(listing["archiveKind"], "lha")
        self.assertIn("LHA archive", listing["description"])
        self.assertEqual([row["name"] for row in listing["entries"]], ["AUTO", "DESKTOP.INF"])
        desktop = listing["entries"][1]
        self.assertEqual(desktop["length"], len(DESKTOP_INF) * 8)
        # A GEMDOS entry records no address of any kind: a program carries its
        # own relocation table and TOS decides where to put it at run time.
        self.assertNotIn("load", desktop)
        self.assertEqual(read_archive_member(blob, "GAME.LZH", "DESKTOP.INF"), DESKTOP_INF * 8)
        self.assertEqual(
            read_archive_member(blob, "GAME.LZH", "AUTO/LOADER.PRG"), GEMDOS_PROGRAM
        )

    @unittest.skipIf(Flask is None, "Flask is installed in the production image")
    def test_archive_routes_mark_browse_and_download_members(self):
        archive_bytes = atari_zip(
            (zip_entry("GAMES/README.TXT", ZIP_HOST_ATARI, 0x20), b"Games collection"),
            (zip_entry("GAMES/DESKTOP.INF", ZIP_HOST_ATARI, 0x21), DESKTOP_INF),
            (zip_entry("GAMES/CODE.BIN", ZIP_HOST_ATARI, 0x20), M68K_CODE),
        )

        class Service:
            session = SimpleNamespace(
                kind="gemdos", target_hardware="floppy", hardware_profile={},
                hfe_read_only=False, partition=None,
            )
            written = None

            def get(self, _image_id):
                return self.session

            def mountable(self, session):
                return session.kind == "gemdos"

            def browse_directory(self, *_args):
                return {"entries": [
                    {"name": "GAMES.ZIP", "type": "file", "length": len(archive_bytes)},
                ]}

            def file_metadata(self, *_args):
                return {"length": len(archive_bytes)}

            def read_file(self, *_args):
                return archive_bytes

            def validate_directory_path(self, prefix):
                from app import atari_paths

                return atari_paths.normalise(prefix)

            def validate_leaf_name(self, _session, name, _slot=None):
                # A GEMDOS name is eight characters and a three character
                # extension, so twelve is the longest one a volume can hold.
                if not name or len(name) > 12:
                    raise DiskError("Invalid GEMDOS filename.")
                return name

            def list_directory(self, *_args):
                return {"entries": []}

            def put(self, _session, destination, host_path, attributes=None,
                    comment=None, filetype=None, side=None, datestamp=None):
                self.written = (
                    destination, host_path.read_bytes(), attributes, datestamp,
                )

            def summary(self, _session):
                return {"id": "test", "kind": "gemdos"}

        service = Service()
        app = Flask(__name__)
        app.register_blueprint(create_files_blueprint(service, Path("/tmp"), OperationRegistry()))
        app.register_blueprint(create_hex_editor_blueprint(service))
        app.register_blueprint(create_tools_blueprint(service, OperationRegistry()))
        app.register_error_handler(DiskError, lambda error: (jsonify(error=str(error)), 400))
        client = app.test_client()
        outer = {"path": "GAMES.ZIP", "name": "GAMES.ZIP"}
        tree = client.get("/api/images/test/tree", query_string={"path": ""}).get_json()
        self.assertTrue(tree["entries"][0]["archive"])
        listing = client.get("/api/images/test/archive/tree", query_string=outer).get_json()
        self.assertEqual(listing["entries"][0]["name"], "GAMES")
        member = client.get(
            "/api/images/test/archive/file",
            query_string=outer | {"member": "GAMES/README.TXT"},
        )
        self.assertEqual(member.data, b"Games collection")
        inspected = client.get(
            "/api/images/test/archive/inspect",
            query_string=outer | {"member": "GAMES/DESKTOP.INF"},
        ).get_json()
        self.assertEqual(inspected["view"], "script")
        self.assertFalse(inspected["readOnly"])
        self.assertTrue(inspected["archiveEditable"])
        self.assertIn("#E9A03", inspected["text"])
        # The entry's own attribute byte travels with the member into the
        # editor, so a locked file is still shown as locked inside an archive.
        self.assertEqual(inspected["metadata"]["attributes"], "r----a")
        disassembly = client.get(
            "/api/images/test/archive/disassembly",
            query_string=outer | {
                "member": "GAMES/CODE.BIN", "architecture": "68000", "origin": "0x8000",
            },
        ).get_json()
        self.assertEqual(disassembly["architecture"], "68000")
        self.assertEqual(disassembly["origin"], 0x8000)
        cheat_report = client.get(
            "/api/images/test/cheat-candidates",
            query_string=outer | {"member": "GAMES/CODE.BIN"},
        ).get_json()
        self.assertEqual(cheat_report["path"], "GAMES/CODE.BIN")
        self.assertEqual(cheat_report["kind"], "68000")
        hex_page = client.get(
            "/api/images/test/archive-hex",
            query_string=outer | {"member": "GAMES/CODE.BIN", "offset": "0", "length": "16"},
        ).get_json()
        self.assertEqual(hex_page["data"], M68K_CODE.hex().upper())
        self.assertTrue(hex_page["readOnly"])
        found = client.get(
            "/api/images/test/archive-hex/search",
            query_string=outer | {
                "member": "GAMES/CODE.BIN", "query": "4E75", "mode": "hex", "start": "0",
            },
        ).get_json()
        self.assertEqual(found["offset"], 6)
        created = client.post("/api/images/test/empty-file", json={
            "destination": "GAMES", "name": "NEWFILE.TXT", "attributes": "r----a",
        })
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.get_json()["path"], "GAMES\\NEWFILE.TXT")
        # The attribute value reaches the service in the form the person typed,
        # which the service parses once rather than each route guessing at it.
        self.assertEqual(
            service.written,
            ("GAMES\\NEWFILE.TXT", b"", "r----a", None),
        )


if __name__ == "__main__":
    unittest.main()
