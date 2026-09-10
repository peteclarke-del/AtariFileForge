"""The online library: its shipped sources, its parsers and its safety rails.

The parser tests declare their own source rather than reaching for a shipped
one, because a parser test is about the shape of a page and not about which
sites happen to be enabled this month. The tests that do name a shipped source
are the ones asserting something about the shipped list itself.

Nothing here goes near the network. The live checks belong in the port report;
a test suite that needs Atarimania to be up is a test suite that fails on a
train.
"""

import io
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from app.catalog_service import (
    CatalogueService,
    DEFAULT_SOURCES,
    MACHINE_ORDER,
    archive_members,
)
from app.errors import DiskError
from app.routes.catalog import (
    MEDIA_PRIORITY,
    _available_ffs_directory_name,
    _catalogue_identities,
    _preferred_disk_members,
)


def source(source_id):
    return next(item for item in DEFAULT_SOURCES if item["id"] == source_id)


def configured_source(source_id, url, **options):
    """Build one catalogue source for a parser test."""
    return {
        "id": source_id, "name": source_id, "type": "configured", "url": url,
        "machines": ["st", "ste", "megaste"], "enabled": True, "direct": True,
        "options": options,
    }


class ShippedSourceTests(unittest.TestCase):
    """What the application offers out of the box, and on which machines."""

    def test_every_shipped_source_names_only_known_machines(self):
        for row in DEFAULT_SOURCES:
            with self.subTest(source=row["id"]):
                self.assertTrue(row["machines"])
                for machine in row["machines"]:
                    self.assertIn(machine, MACHINE_ORDER)

    def test_a_disabled_source_says_why(self):
        """A source nobody can reach must explain itself, not fail silently."""
        for row in DEFAULT_SOURCES:
            if not row["enabled"]:
                with self.subTest(source=row["id"]):
                    self.assertTrue(str(row.get("disabledReason") or "").strip())

    def test_the_shipped_sources_are_the_st_ones(self):
        self.assertEqual(
            {row["id"] for row in DEFAULT_SOURCES},
            {"internet-archive-st-games", "demozoo", "pigwa", "atarimania", "atari-legend"},
        )

    def test_a_reference_database_is_not_offered_as_a_download(self):
        for source_id in ("atarimania", "atari-legend"):
            with self.subTest(source=source_id):
                self.assertFalse(source(source_id)["direct"])


class CatalogueServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = CatalogueService(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    @patch("app.catalog_service.urllib.request.urlopen")
    def test_fetch_rejects_non_http_url_before_opening_it(self, urlopen):
        with self.assertRaisesRegex(DiskError, "invalid URL"):
            self.service._fetch("file:///etc/passwd")
        urlopen.assert_not_called()

    def test_online_install_source_name_matches_catalogue_title(self):
        self.assertIn("oids", _catalogue_identities("Oids (Faster Than Light).st"))
        self.assertTrue(
            _catalogue_identities("Bad Company")
            & _catalogue_identities("Bad_Company (Logotron).st")
        )

    def test_source_configuration_is_validated_and_persisted(self):
        rows = self.service.save_sources([{
            "id": "mine", "name": "Mine", "type": "links",
            "url": "https://example.test/catalogue", "machines": ["st"], "enabled": True,
        }])
        self.assertEqual(rows[0]["id"], "mine")
        restarted = CatalogueService(self.temporary.name)
        self.assertEqual(restarted.sources()[0]["url"], "https://example.test/catalogue")
        # The shipped sources are added back, and a source this application
        # has never shipped does not appear from nowhere.
        self.assertIn("pigwa", {row["id"] for row in restarted.sources()})
        self.assertNotIn("a-source-never-shipped", {row["id"] for row in restarted.sources()})
        with self.assertRaises(DiskError):
            self.service.save_sources([{"name": "Unsafe", "url": "file:///etc/passwd"}])

    def test_new_default_settings_are_merged_without_overwriting_configuration(self):
        configured = copy.deepcopy(source("internet-archive-st-games"))
        configured["options"].pop("metadataUrl")
        configured["options"]["rows"] = 10
        self.service.save_sources([configured])
        loaded = next(
            row for row in self.service.sources() if row["id"] == "internet-archive-st-games"
        )
        self.assertEqual(loaded["options"]["metadataUrl"], "https://archive.org/metadata/{identifier}")
        self.assertEqual(loaded["options"]["rows"], 10)

    def test_catalogue_result_survives_service_restart(self):
        token = "a" * 32
        expected = {"title": "Oids", "downloadUrl": "https://example.test/oids.st"}
        self.service._remember_item(token, expected)

        self.assertEqual(CatalogueService(self.temporary.name).item(token), expected)

    def test_search_is_sent_to_the_complete_remote_catalogue(self):
        body = b'''<div class="thumbnail"><div class="row-title"><a href="game.php?id=1">Oids</a></div>
          <div class="row-pub"><a>FTL</a></div><div class="row-dt"><a>1987</a></div>
          <a href="images/1/oids.st">Download</a></div></div>'''
        requested = []
        self.service.save_sources([configured_source(
            "cards", "https://games.example/",
            loader="page", parser="thumbnail-cards", queryTemplate="index.php?search={query}",
        )])
        self.service._fetch = lambda url, **_options: requested.append(url) or body
        rows, failures = self.service.search("Oids", "st", {"cards"})
        self.assertFalse(failures)
        self.assertEqual(rows[0]["title"], "Oids")
        self.assertIn("search=oids", requested[0])

    def test_pipeline_uses_configuration_not_catalogue_identity(self):
        configured = configured_source(
            "cards", "https://games.example/", loader="page", parser="thumbnail-cards",
        )
        configured.update(id="arbitrary-provider", name="Arbitrary Provider", url="https://example.test/")
        self.service.save_sources([configured])
        self.service._fetch = lambda *_args, **_options: b'''<div class="thumbnail">
          <div class="row-title"><a href="game.php?id=1">Configured Game</a></div>
          <a href="files/configured.st">Download</a></div></div>'''
        rows, failures = self.service.search("Configured", "st", {"arbitrary-provider"})
        self.assertFalse(failures)
        self.assertEqual(rows[0]["title"], "Configured Game")
        self.assertEqual(rows[0]["sourceName"], "Arbitrary Provider")

    def test_a_reference_source_still_returns_its_rows(self):
        """A source marked as not direct exists to answer "what is this".

        The search drops a direct source's row when it has no media behind it,
        because offering it would fail at install. A reference database never
        has media, so the same rule would silently empty it.
        """
        configured = configured_source("reference", "https://database.example/")
        configured["direct"] = False
        configured["options"] = {"loader": "page", "parser": "links", "linkPattern": "/games/"}
        self.service.save_sources([configured])
        self.service._fetch = lambda *_args, **_options: (
            b'<a href="/games/oids">Oids</a><a href="/help">Help</a>'
        )
        rows, failures = self.service.search("oids", "st", {"reference"})
        self.assertFalse(failures)
        self.assertEqual([row["title"] for row in rows], ["Oids"])
        self.assertEqual(rows[0]["artifactType"], "external")

    def test_resolver_catalogues_return_continuation_without_claiming_unchecked_media(self):
        configured = copy.deepcopy(source("internet-archive-st-games"))
        configured["options"]["resultValidationLimit"] = 2
        candidates = [
            {
                "title": f"Game {number}", "publisher": "Publisher", "description": "",
                "year": "", "downloadable": True, "resolver": "archive-files",
                "pageUrl": f"https://example.test/game/{number}", "downloadUrl": None,
                "artifactType": "disk-image", "machines": ["st"],
            }
            for number in range(5)
        ]
        self.service.sources = lambda: [configured]
        self.service._load_catalogue = lambda *_args: [dict(row) for row in candidates]
        self.service._resolve_row = lambda row: {**row, "downloadUrl": f"{row['pageUrl']}.st"}

        first, failures, continuation = self.service.search_page("", "st")
        second, _, next_continuation = self.service.search_page("", "st", cursors=continuation)

        self.assertEqual([row["title"] for row in first], ["Game 0", "Game 1"])
        self.assertEqual([row["title"] for row in second], ["Game 2", "Game 3"])
        self.assertEqual(failures, [])
        self.assertEqual(continuation, {"internet-archive-st-games": 2})
        self.assertEqual(next_continuation, {"internet-archive-st-games": 4})

    def test_online_ffs_directory_allocator_avoids_existing_truncated_names(self):
        service = Mock()
        service.list_directory.return_value = {
            "entries": [{"name": "LONGTITLE"}, {"name": "LONGTITLE1"}],
        }
        name = _available_ffs_directory_name(service, Mock(), "$.Games", "LONGTITLE")
        self.assertEqual(name, "LONGTITLE2")

    def test_archive_members_rejects_traversal_and_keeps_images(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("games/oids.st", b"disk")
            archive.writestr("../escape.st", b"bad")
        self.assertEqual(
            archive_members("games.zip", buffer.getvalue()), [("games/oids.st", b"disk")]
        )

    def test_the_plain_image_is_preferred_over_its_packed_variant(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Oids.st", b"st")
            archive.writestr("Oids.msa", b"msa")
        self.assertEqual(
            _preferred_disk_members("oids.zip", buffer.getvalue()), [("Oids.st", b"st")]
        )

    def test_the_install_media_priority_is_the_st_one(self):
        self.assertEqual(
            MEDIA_PRIORITY,
            {".st": 0, ".msa": 1, ".stx": 2, ".dim": 3, ".hfe": 4, ".scp": 5, ".zip": 6},
        )

    def test_a_download_is_chosen_by_format_and_by_what_was_asked_for(self):
        choices = [
            "https://example.test/Oids.zip",
            "https://example.test/Oids.msa",
            "https://example.test/Oids.st",
        ]
        self.assertEqual(
            max(choices, key=lambda url: self.service._download_score(url, ".st")),
            "https://example.test/Oids.st",
        )
        self.assertEqual(
            max(choices, key=lambda url: self.service._download_score(url, ".msa")),
            "https://example.test/Oids.msa",
        )


class InternetArchiveTests(unittest.TestCase):
    """The Internet Archive's ST collection, read through its JSON APIs."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = CatalogueService(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.source = copy.deepcopy(source("internet-archive-st-games"))

    def test_the_search_is_restricted_to_the_configured_collection(self):
        requested = []
        self.service._fetch = lambda url, **_options: requested.append(url) or (
            b'{"response": {"docs": []}}'
        )
        self.service._load_internet_archive(self.source, "bad company", "st")
        self.assertIn("collection%3Asoftwarelibrary_atari_st_games", requested[0])
        self.assertIn("title%3A%28bad+company%29", requested[0])

    def test_index_syntax_in_the_search_box_cannot_reach_the_query(self):
        """A person's typing is words, not a query language."""
        requested = []
        self.service._fetch = lambda url, **_options: requested.append(url) or (
            b'{"response": {"docs": []}}'
        )
        self.service._load_internet_archive(self.source, 'oids") OR identifier:(*', "st")
        self.assertIn("title%3A%28oids+OR+identifier%29", requested[0])

    def test_a_record_becomes_a_row_that_still_has_to_be_resolved(self):
        body = json.dumps({"response": {"docs": [{
            "identifier": "Bad_Company_1989_Logotron_cr",
            "title": "Bad Company",
            "creator": "Logotron",
            "date": "1989-01-01T00:00:00Z",
        }]}})
        row = self.service._parse_archive_documents(self.source, body, {})[0]
        self.assertEqual(row["title"], "Bad Company")
        self.assertEqual(row["publisher"], "Logotron")
        self.assertEqual(row["year"], "1989")
        self.assertIsNone(row["downloadUrl"])
        self.assertEqual(row["resolver"], "archive-files")
        self.assertEqual(
            row["resolverOptions"]["metadataUrl"],
            "https://archive.org/metadata/Bad_Company_1989_Logotron_cr",
        )

    def test_the_resolver_keeps_disk_images_and_drops_the_sidecars(self):
        row = {
            "title": "Bad Company", "description": "", "resolver": "archive-files",
            "resolverOptions": {
                "metadataUrl": "https://archive.org/metadata/BadCo",
                "downloadTemplate": "https://archive.org/download/BadCo/{name}",
                "mediaExtensions": ["st", "msa", "stx", "dim", "zip"],
            },
        }
        self.service._fetch = lambda *_args, **_kwargs: json.dumps({"files": [
            {"name": "BadCo_meta.xml"},
            {"name": "BadCo_archive.torrent"},
            {"name": "screenshot_00.png"},
            {"name": "Bad Company.st"},
        ]}).encode()
        resolved = self.service._resolve_row(row)
        self.assertEqual(
            resolved["downloadChoices"],
            ["https://archive.org/download/BadCo/Bad%20Company.st"],
        )

    def test_an_item_with_no_disk_image_is_suppressed(self):
        row = {
            "title": "Cover scans", "description": "", "resolver": "archive-files",
            "resolverOptions": {
                "metadataUrl": "https://archive.org/metadata/Scans",
                "downloadTemplate": "https://archive.org/download/Scans/{name}",
                "mediaExtensions": ["st", "msa"],
            },
        }
        self.service._fetch = lambda *_args, **_kwargs: b'{"files": [{"name": "cover.jpg"}]}'
        self.assertIsNone(self.service._resolve_row(row))


class DemozooTests(unittest.TestCase):
    """Demozoo's production API, recorded rather than fetched."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = CatalogueService(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.source = copy.deepcopy(source("demozoo"))

    #: One production, as the API really answered on the day this was written.
    LISTING = json.dumps({"count": 1, "results": [{
        "url": "https://demozoo.org/api/v1/productions/76257/?format=json",
        "demozoo_url": "https://demozoo.org/productions/76257/",
        "id": 76257,
        "title": "Cuddly Demos",
        "author_nicks": [{"name": "The Carebears", "abbreviation": "TCB"}],
        "release_date": "1989-12-27",
        "supertype": "production",
        "platforms": [{"id": 9, "name": "Atari ST/E"}],
        "types": [{"id": 1, "name": "Demo"}],
    }]})

    def test_each_configured_platform_is_asked_separately(self):
        requested = []
        self.service._fetch = lambda url, **_options: requested.append(url) or b'{"results": []}'
        self.service._load_demozoo(self.source, "cuddly", "all")
        self.assertEqual(
            sorted(requested),
            sorted(
                f"https://demozoo.org/api/v1/productions/?platform={identifier}"
                "&title=cuddly&format=json"
                for identifier in (9, 58, 17)
            ),
        )

    def test_one_machine_asks_only_for_its_own_platform(self):
        requested = []
        self.service._fetch = lambda url, **_options: requested.append(url) or b'{"results": []}'
        self.service._load_demozoo(self.source, "cuddly", "falcon030")
        self.assertEqual(len(requested), 1)
        self.assertIn("platform=17", requested[0])

    def test_a_production_becomes_a_row_carrying_its_own_record(self):
        row = self.service._parse_demozoo_productions(self.source, self.LISTING, {})[0]
        self.assertEqual(row["title"], "Cuddly Demos")
        self.assertEqual(row["publisher"], "The Carebears")
        self.assertEqual(row["year"], "1989")
        self.assertEqual(row["machines"], ["st", "megast", "ste", "megaste"])
        self.assertEqual(
            row["resolverOptions"]["detailUrl"],
            "https://demozoo.org/api/v1/productions/76257/?format=json",
        )

    def test_the_resolver_keeps_st_media_and_drops_another_machine_s(self):
        row = {
            "title": "Cuddly Demos", "description": "",
            "resolver": "demozoo-downloads",
            "resolverOptions": {"detailUrl": "https://demozoo.org/api/v1/productions/76257/?format=json"},
        }
        self.service._fetch = lambda *_args, **_kwargs: json.dumps({"download_links": [
            {"link_class": "BaseUrl", "url": "http://wt.example/RIP_CuddlyDemos.lzx"},
            {"link_class": "FujiologyFile", "url": "https://fujiology.example/ST/T/TCB/CUDDLY.ZIP"},
        ]}).encode()
        resolved = self.service._resolve_row(row)
        self.assertEqual(
            resolved["downloadChoices"], ["https://fujiology.example/ST/T/TCB/CUDDLY.ZIP"]
        )

    def test_a_production_with_nothing_downloadable_is_suppressed(self):
        row = {
            "title": "A tune", "description": "",
            "resolver": "demozoo-downloads",
            "resolverOptions": {"detailUrl": "https://demozoo.org/api/v1/productions/1/?format=json"},
        }
        self.service._fetch = lambda *_args, **_kwargs: (
            b'{"download_links": [{"url": "https://media.example/cuddly.MOD"}]}'
        )
        self.assertIsNone(self.service._resolve_row(row))


class DirectoryListingTests(unittest.TestCase):
    """One level of an ordinary web server index, which is how Pigwa serves."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = CatalogueService(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.source = copy.deepcopy(source("pigwa"))

    INDEX = (
        b'<a href="/welcome.msg">welcome.msg</a>'
        b'<a href="?C=N;O=D">Name</a>'
        b'<a href="/stuff/collections/">Parent Directory</a>'
        b'<a href="Pompey%20Pirates%20FIXED/">Pompey Pirates FIXED/</a>'
        b'<a href="https://www.patreon.com/pigwa">patreon</a>'
    )
    FOLDER = (
        b'<a href="/welcome.msg">welcome.msg</a>'
        b'<a href="?C=S;O=A">Size</a>'
        b'<a href="../">Parent Directory</a>'
        b'<a href="!!!%20PP%20List.txt">!!! PP List.txt</a>'
        b'<a href="Pompey%20Pirates%20Menu%20Disk%20001%20(19xx)(Pompey%20Pirates).st">Disk 1</a>'
    )

    def _pages(self, url, **_options):
        return self.FOLDER if "FIXED" in url else self.INDEX

    def test_only_the_folders_of_the_index_are_crawled(self):
        requested = []

        def fetch(url, **options):
            requested.append(url)
            return self._pages(url, **options)

        self.service._fetch = fetch
        self.service._load_directory_listing(self.source, "", "st")
        self.assertEqual(requested, [
            self.source["url"],
            self.source["url"] + "Pompey%20Pirates%20FIXED/",
        ])

    def test_a_disk_image_becomes_a_row_and_a_text_file_does_not(self):
        self.service._fetch = self._pages
        rows = self.service._load_directory_listing(self.source, "", "st")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Pompey Pirates Menu Disk 001 (19xx)(Pompey Pirates)")
        self.assertEqual(rows[0]["publisher"], "Pompey Pirates FIXED")
        self.assertTrue(rows[0]["downloadUrl"].endswith("(Pompey%20Pirates).st"))

    def test_the_crawled_catalogue_is_only_built_once(self):
        calls = []

        def fetch(url, **options):
            calls.append(url)
            return self._pages(url, **options)

        self.service._fetch = fetch
        self.service._load_directory_listing(self.source, "", "st")
        self.service._load_directory_listing(self.source, "", "st")
        self.assertEqual(len(calls), 2)


class CatalogueParserTests(unittest.TestCase):
    """The parsers, against the shapes real archives actually serve."""

    @staticmethod
    def _service(folder):
        return CatalogueService(Path(folder))

    def test_relative_result_links_are_resolved_against_the_page(self) -> None:
        """A site links its own results relatively, and those are the results."""
        source_row = {
            "id": "example", "name": "Example", "url": "https://example.test/",
            "options": {"linkPattern": "/games/"},
        }
        body = (
            '<a href="https://sponsor.test/ad">Buy something</a>'
            '<a href="/games/oids">Oids</a>'
            '<a href="/games/blasteroids">Blasteroids</a>'
            '<a href="/search/advanced.php">Go to Advanced Search</a>'
        )
        with tempfile.TemporaryDirectory() as folder:
            rows = self._service(folder)._parse_links(
                source_row, body, {"url": "https://example.test/search?title=oids"},
            )
        self.assertEqual(
            [row["pageUrl"] for row in rows],
            ["https://example.test/games/oids", "https://example.test/games/blasteroids"],
        )
        # linkPattern is what keeps the advert and the navigation out.
        self.assertEqual([row["title"] for row in rows], ["Oids", "Blasteroids"])

    def test_links_without_a_pattern_still_exclude_fragments(self) -> None:
        source_row = {"id": "example", "name": "Example", "url": "https://example.test/", "options": {}}
        body = '<a href="#top">Top</a><a href="/one.html">One</a>'
        with tempfile.TemporaryDirectory() as folder:
            rows = self._service(folder)._parse_links(source_row, body, {"url": "https://example.test/"})
        self.assertEqual([row["pageUrl"] for row in rows], ["https://example.test/one.html"])

    def test_a_database_row_is_read_apart_into_title_publisher_and_year(self) -> None:
        """Atarimania writes the facts inside the result anchor, in two spans."""
        body = (
            '<li><a class="flex" href="/games/atari-st-games-oids-10116">'
            '<span class="text-sm text-ink">Oids'
            '<span class="ml-2 text-teal">Atari ST</span></span>'
            '<span class="font-mono text-xs">'
            "Shoot&#x27;em Up! - Multi-Directional · Faster than Light (FTL) · USA · 1987"
            "</span></a></li>"
            '<li><a href="/magazines">Magazines</a></li>'
        )
        with tempfile.TemporaryDirectory() as folder:
            rows = self._service(folder)._parse_database_rows(
                {
                    "id": "atarimania", "name": "Atarimania", "url": "https://www.atarimania.com/",
                    "machines": ["st"],
                    "options": {"linkPattern": "/games/atari-st-games-", "detailSeparator": "·"},
                },
                body,
                {"url": "https://www.atarimania.com/search?q=oids&m=S"},
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Oids")
        self.assertEqual(rows[0]["publisher"], "Faster than Light (FTL)")
        self.assertEqual(rows[0]["year"], "1987")
        self.assertFalse(rows[0]["downloadable"])

    def test_a_database_row_with_nobody_credited_reports_no_publisher(self) -> None:
        body = (
            '<a href="/games/atari-st-games-asteroids-11118">'
            '<span>Asteroids<span>Atari ST</span></span>'
            "<span>Shoot&#x27;em Up! · [no publisher] · UK · 1992</span></a>"
        )
        with tempfile.TemporaryDirectory() as folder:
            rows = self._service(folder)._parse_database_rows(
                {
                    "id": "atarimania", "name": "Atarimania", "url": "https://www.atarimania.com/",
                    "machines": ["st"], "options": {"linkPattern": "/games/atari-st-games-"},
                },
                body,
                {},
            )
        self.assertEqual(rows[0]["publisher"], "")
        self.assertEqual(rows[0]["year"], "1992")

    def test_an_escaped_ampersand_is_not_part_of_the_address(self) -> None:
        """An href is HTML: ``&amp;`` in a query string is one ampersand."""
        source_row = {
            "id": "example", "name": "Example", "url": "https://example.test/",
            "options": {"rowResolver": "media-links", "resolverOptions": {"downloadPathContains": "/files/"}},
        }
        body = "<A HREF='?function=showfile&amp;file=games/oids.st'>Oids</A>"
        with tempfile.TemporaryDirectory() as folder:
            rows = self._service(folder)._parse_zip_links(source_row, body, {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["pageUrl"], "https://example.test/?function=showfile&file=games/oids.st",
        )
        # A row the resolver has to follow carries the page, not a download
        # address that would fetch a description instead of the file.
        self.assertIsNone(rows[0]["downloadUrl"])
        self.assertEqual(rows[0]["resolverOptions"], {"downloadPathContains": "/files/"})
        self.assertTrue(rows[0]["downloadable"])

    def test_a_form_post_source_needs_its_fields(self) -> None:
        source_row = {
            "id": "example", "name": "Example", "url": "https://example.test/",
            "options": {"loader": "form-post", "queryTemplate": "search.php"},
        }
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(DiskError, "search form fields"):
                self._service(folder)._load_form_post(source_row, "oids", "st")


class MachineCompatibilityTests(unittest.TestCase):
    """Turning a catalogue's compatibility prose into machine filters."""

    def test_plain_st_software_is_offered_on_every_st(self):
        from app.catalog_service import _machines_from_compatibility

        self.assertEqual(
            _machines_from_compatibility("Atari ST", []),
            ["st", "megast", "ste", "megaste"],
        )

    def test_an_ste_release_is_not_offered_on_a_plain_st(self):
        from app.catalog_service import _machines_from_compatibility

        self.assertEqual(_machines_from_compatibility("Atari STE", []), ["ste", "megaste"])

    def test_a_two_word_model_is_not_read_as_the_shorter_one(self):
        """"Mega STE" contains both "megast" and "st", and is neither."""
        from app.catalog_service import _machines_from_compatibility

        self.assertEqual(_machines_from_compatibility("Mega STE", []), ["megaste"])
        self.assertEqual(_machines_from_compatibility("Mega ST", []), ["megast"])

    def test_the_thirty_two_bit_machines_are_recognised(self):
        from app.catalog_service import _machines_from_compatibility

        self.assertEqual(
            _machines_from_compatibility("Falcon030 / TT", []), ["tt030", "falcon030"]
        )

    def test_prose_naming_nothing_falls_back_to_the_source(self):
        from app.catalog_service import _machines_from_compatibility

        self.assertEqual(_machines_from_compatibility("Floppy, English", ["st"]), ["st"])


if __name__ == "__main__":
    unittest.main()
