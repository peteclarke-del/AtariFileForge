"""Filename and online metadata discovery for imported Atari ST software.

Almost every ST disk image in circulation is named in one of two styles, and
both of them carry more than the title. TOSEC writes
``Title (Year)(Publisher)(Country)[cr Group][a]``; the Internet Archive's ST
collection writes the same facts with underscores,
``Title_1988_Publisher_cr_TDA``. Reading those apart is usually the difference
between an import that knows what it is and one that shows an eight-character
GEMDOS name.

The bracketed and trailing parts are distribution facts rather than title
facts. ``[cr Automation]`` says who cracked it, ``[a]`` says this is an
alternate dump, ``[h]`` that it was hacked. They are recorded, because a
Pompey Pirates or D-Bug release is a different artefact from the original
disk, and they are kept out of the title, because nobody looks up a game
called "Xenon (1988)(Melbourne House)[cr Replicants]".
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

from .outbound import checked_url


#: The Internet Archive's ST collections are the searchable record of what was
#: released, and the only one of these three that answers a query in JSON.
ARCHIVE_ORG_SEARCH = "https://archive.org/advancedsearch.php"

#: Atarimania catalogues ST releases with publisher, country and year.
ATARIMANIA_SEARCH = "https://www.atarimania.com/search"

#: Atari Legend catalogues the same ground with its own attributions.
ATARI_LEGEND_SEARCH = "https://www.atarilegend.com/games/search"

_USER_AGENT = "AtariFileForge/1.0 metadata lookup"

#: Every container an ST release is distributed in. The suffix is stripped
#: before the name is read, and stripped repeatedly because ``.st.zip`` and
#: ``.msa.zip`` are both common.
_DISTRIBUTION_SUFFIXES = {
    ".zip", ".st", ".msa", ".stx", ".dim", ".hfe", ".scp", ".ipf",
    ".img", ".raw", ".stt", ".mfm",
}

#: The groups whose name in a filename says how a disk was distributed rather
#: than who published the game. A cracked release is a real artefact worth
#: recording; it is not the publisher, and it is not part of the title.
_SCENE_GROUPS = (
    "automation",
    "pompey pirates",
    "medway boys",
    "d-bug",
    "dbug",
    "fuzion",
    "replicants",
    "elite",
    "the automation",
    "empire",
)

#: What a TOSEC tag says about the dump itself.
_TOSEC_TAGS = {
    "a": "alternate dump",
    "b": "bad dump",
    "h": "hacked",
    "o": "overdump",
    "t": "trained",
}

#: A country or region in the publisher position is not a publisher.
_REGIONS = re.compile(
    r"(?:UK|US|USA|EU|EUR|Europe|World|GB|DE|FR|ES|IT|JP|AU|NL|SE|PL|CZ|FI|DK|NO|"
    r"En|Fr|De|Es|It|Sv|Nl|Pl|Cz|Da|No|Fi|"
    r"ST|STE|Mega ST|Mega STE|TT|Falcon|Falcon030|Atari|Atari ST)",
    re.I,
)

#: A version or disk-number field is not a publisher either.
_NOT_A_PUBLISHER = re.compile(
    r"(?:v?\d+(?:\.\d+)*[a-z]?|disk\s*\d+|disc\s*\d+|side\s*[ab12]|"
    r"one\s*disk|two\s*disks|hd|floppy|-)",
    re.I,
)


def _distribution_facts(text: str) -> tuple[list[str], list[str]]:
    """Read the cracking group and dump tags out of a filename's tail.

    Both naming styles are handled at once, because the same release turns up
    under both: ``[cr Pompey Pirates]`` in a TOSEC set and ``_cr_TDA`` in the
    Internet Archive's, with the underscores standing in for the brackets that
    a filesystem of the day could not carry.
    """
    value = str(text or "")
    # An underscore stands in for a space in the Internet Archive's names, so
    # both styles are read as words once the separators are levelled.
    spaced = re.sub(r"[_\s]+", " ", value)
    lowered = spaced.casefold()
    groups: list[str] = []
    for name in _SCENE_GROUPS:
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", lowered):
            spelled = "D-Bug" if name in {"d-bug", "dbug"} else name.title()
            if spelled not in groups:
                groups.append(spelled)
    # "cr" names a cracker whose group this list does not know; the abbreviation
    # that follows it is worth keeping even when the name is not recognised.
    for match in re.finditer(r"(?<![A-Za-z0-9])cr\s+([A-Za-z][A-Za-z0-9&'.\-]{1,24})", spaced, re.I):
        candidate = match.group(1).strip(" -")
        known = {name.casefold() for name in groups}
        if candidate and candidate.casefold() not in known and not any(
            candidate.casefold() in name for name in known
        ):
            groups.append(candidate)
    # A single-letter dump tag is only read after the release year, because a
    # bare "a" or "t" earlier in the string is a word of the title.
    year = re.search(r"(?:19|20)[0-9x]{2}", spaced)
    tail = spaced[year.end():] if year else ""
    tags = [
        description
        for letter, description in _TOSEC_TAGS.items()
        if re.search(rf"\[{letter}\d*(?:\s[^\]]*)?\]", value, re.I)
        or re.search(rf"(?<![A-Za-z0-9]){letter}\d*(?![A-Za-z0-9])", tail, re.I)
    ]
    return list(dict.fromkeys(groups)), tags


def _plausible_publisher(candidate: str) -> bool:
    value = str(candidate or "").strip()
    if not value or len(value) > 60:
        return False
    if _REGIONS.fullmatch(value) or _NOT_A_PUBLISHER.fullmatch(value):
        return False
    return bool(re.search(r"[A-Za-z]", value))


def _title_case(value: str) -> str:
    """Move a trailing article back to the front, as a catalogue spells it."""
    article = re.fullmatch(r"(.+),\s*(The|A|An|Le|La|Les|Der|Die|Das)", value, re.I)
    return f"{article.group(2)} {article.group(1)}" if article else value


def parse_distribution_filename(filename: str) -> dict:
    """Extract cautious TOSEC or Internet Archive metadata from a host filename.

    Nothing here is guessed at. A field that cannot be read confidently is
    returned empty, because an invented publisher is worse than none: it looks
    like a fact and is carried forward into the catalogue as one.
    """
    name = Path(str(filename or "").replace("\\", "/")).name
    stem = name
    while Path(stem).suffix.lower() in _DISTRIBUTION_SUFFIXES:
        stem = Path(stem).stem
    groups, tags = _distribution_facts(stem)
    # Everything from the first bracket onwards describes the dump, not the
    # release, so it is read separately and then cut away.
    trimmed = re.sub(r"\s*\[[^\]]*]", "", stem).strip()
    bracketed = [value.strip() for value in re.findall(r"\(([^()]*)\)", trimmed)]
    title = ""
    year = ""
    publisher = ""

    if bracketed:
        title = re.sub(r"[_\s]+", " ", re.split(r"\s*\(", trimmed, maxsplit=1)[0]).strip(" ._-")
        date_index = next(
            (
                offset
                for offset, value in enumerate(bracketed)
                if re.fullmatch(r"(?:19|20)[0-9x]{2}(?:-[0-9x]{2}(?:-[0-9x]{2})?)?", value, re.I)
            ),
            None,
        )
        if date_index is not None:
            year = bracketed[date_index]
            following = bracketed[date_index + 1:]
            publisher = next((value for value in following if _plausible_publisher(value)), "")
    else:
        # The underscore style: Title_Year_Publisher_cr_Group. The year is the
        # hinge, because the title before it may be several words and the
        # distribution fields after it may be any number of them.
        fields = [field for field in re.split(r"_+", trimmed) if field]
        year_index = next(
            (offset for offset, value in enumerate(fields) if re.fullmatch(r"(?:19|20)[0-9x]{2}", value, re.I)),
            None,
        )
        if year_index is not None:
            title = " ".join(fields[:year_index]).strip(" ._-")
            year = fields[year_index]
            publisher = next(
                (value for value in fields[year_index + 1:] if _plausible_publisher(value)),
                "",
            )
        else:
            title = re.sub(r"[_\s]+", " ", trimmed).strip(" ._-")

    if re.fullmatch(r"ZZZ[-_ ]UNK.*", title, re.I):
        title = ""
    title = _title_case(title)
    # A version marker belongs to the release, not to the name of the game.
    title = re.sub(r"\s+v\d+(?:\.\d+)*[a-z]?$", "", title, flags=re.I).strip()
    if publisher.casefold() in {group.casefold() for group in groups}:
        publisher = ""
    return {
        "title": title,
        "year": year,
        "publisher": publisher,
        "groups": groups,
        "tags": tags,
        "sourceFilename": name,
    }


def best_distribution_filename(filenames: list[str]) -> str:
    """Prefer the archive or member name carrying the richest usable metadata."""
    candidates = [str(name) for name in filenames if name]
    if not candidates:
        return ""
    parsed = [(name, parse_distribution_filename(name)) for name in candidates]
    return max(
        parsed,
        key=lambda item: (
            bool(item[1]["publisher"]),
            bool(item[1]["year"]),
            len(item[1]["title"]),
        ),
    )[0]


def enrich_from_distribution_filename(metadata: dict, filename: str) -> dict:
    """Apply distribution-name facts before an ambiguous online lookup."""
    parsed = parse_distribution_filename(filename)
    facts = []
    if parsed["title"]:
        metadata["title"] = parsed["title"]
        metadata["confidence"] = min(100, int(metadata.get("confidence", 0)) + 15)
        facts.append(f"title “{parsed['title']}”")
    if parsed["publisher"]:
        metadata["publisher"] = parsed["publisher"]
        metadata["confidence"] = min(100, int(metadata.get("confidence", 0)) + 10)
        facts.append(f"publisher “{parsed['publisher']}”")
    if parsed["year"]:
        metadata["year"] = parsed["year"]
        metadata["confidence"] = min(100, int(metadata.get("confidence", 0)) + 5)
        facts.append(f"date {parsed['year']}")
    if parsed["groups"]:
        metadata["distributionGroups"] = list(parsed["groups"])
        facts.append("released by " + ", ".join(parsed["groups"]))
    if parsed["tags"]:
        metadata["distributionTags"] = list(parsed["tags"])
        facts.append("marked " + ", ".join(parsed["tags"]))
    if facts:
        metadata.setdefault("evidence", []).append(
            f"Distribution filename {parsed['sourceFilename']} supplied " + ", ".join(facts)
        )
        metadata["distributionFilename"] = parsed["sourceFilename"]
        metadata["ambiguous"] = (
            int(metadata.get("confidence", 0)) < 75 or not metadata.get("filename")
        )
    return metadata


def _plain_text(source: str) -> str:
    source = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", source)
    source = re.sub(r"(?s)<[^>]+>", "\n", source)
    return re.sub(r"[ \t]+", " ", html.unescape(source))


def _read(url: str, timeout: float, limit: int = 1_000_000) -> str:
    """Fetch one lookup page under the shared outbound network policy."""
    request = urllib.request.Request(checked_url(url), headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(limit).decode("utf-8", "replace")


def _lookup_archive_org(query: str, timeout: float) -> list[dict]:
    """Search the Internet Archive's ST software collections."""
    terms = " ".join(re.findall(r"[A-Za-z0-9]+", query)[:8])
    if not terms:
        return []
    parameters = urllib.parse.urlencode(
        {
            "q": f"collection:softwarelibrary_atari_st_games AND title:({terms})",
            "fl[]": ["identifier", "title", "creator", "date"],
            "rows": 5,
            "page": 1,
            "output": "json",
        },
        doseq=True,
    )
    payload = json.loads(_read(f"{ARCHIVE_ORG_SEARCH}?{parameters}", timeout))
    results = []
    for item in payload.get("response", {}).get("docs", []):
        identifier = str(item.get("identifier") or "")
        if not identifier:
            continue
        creator = item.get("creator")
        results.append({
            "title": str(item.get("title") or query),
            "publisher": ", ".join(str(value) for value in creator) if isinstance(creator, list) else str(creator or ""),
            "year": str(item.get("date") or "")[:4],
            "url": f"https://archive.org/details/{urllib.parse.quote(identifier)}",
            "source": "Internet Archive",
        })
    return results


def _lookup_atarimania(query: str, timeout: float) -> list[dict]:
    """Search Atarimania's ST database.

    ``m=S`` is how the site's own result tabs narrow a search to the ST, which
    matters because the database also covers the 2600, 5200, 7800, 8-bit,
    Lynx and Jaguar and a title such as "Asteroids" exists on most of them.
    """
    url = f"{ATARIMANIA_SEARCH}?q={urllib.parse.quote_plus(query)}&m=S"
    source = _read(url, timeout)
    results = []
    for href, inner in re.findall(
        r'(?is)<a\s[^>]*href=["\'](/games/atari-st-games-[^"\']+)["\'][^>]*>(.*?)</a>',
        source,
    ):
        spans = re.findall(r"(?is)<span[^>]*>(.*?)</span>", inner)
        # The machine badge is a span nested in the title span, so the title
        # is what stands before it rather than the whole of the first span.
        title = re.sub(
            r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.split(r"<span", spans[0], maxsplit=1)[0]))
        ).strip() if spans else ""
        if not title:
            continue
        details = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", spans[-1]))).strip() if len(spans) > 1 else ""
        fields = [part.strip() for part in details.split("·") if part.strip()]
        publisher = fields[1] if len(fields) > 1 else ""
        if re.fullmatch(r"(?:19|20)\d{2}", publisher) or publisher.casefold() == "[no publisher]":
            publisher = ""
        year = re.search(r"\b(?:19|20)\d{2}\b", details)
        results.append({
            "title": title,
            "publisher": publisher,
            "year": year.group(0) if year else "",
            "url": urllib.parse.urljoin("https://www.atarimania.com/", href),
            "source": "Atarimania",
        })
        if len(results) == 5:
            break
    return results


def _lookup_atari_legend(query: str, timeout: float) -> list[dict]:
    """Search Atari Legend, whose results name the developer beside the game."""
    url = f"{ATARI_LEGEND_SEARCH}?title={urllib.parse.quote_plus(query)}"
    source = _read(url, timeout, limit=2_000_000)
    # Every game link on the page is read first, in order, and then the results
    # are picked out of them. Matching a title and its developer in one
    # expression makes the regular expression backtrack across the whole page
    # and drag half of it into the title.
    anchors = [
        (
            match.group(1),
            re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", match.group(2)))).strip(),
            match.end(),
        )
        for match in re.finditer(
            r'(?is)<a\s[^>]*href=["\'](https://www\.atarilegend\.com/games/[^"\'/?#]+)["\'][^>]*>(.*?)</a>',
            source,
        )
    ]
    results = []
    seen: set[str] = set()
    for first, second in zip(anchors, anchors[1:]):
        # A result is a screenshot link immediately followed by a text link to
        # the same game. The page furniture -- the recent-activity panel and
        # the related-games strip -- links each game only once, so this is what
        # separates the search's answers from the rest of the page.
        if first[0] != second[0] or first[1] or not second[1] or second[0] in seen:
            continue
        seen.add(second[0])
        window = source[second[2]:second[2] + 400]
        developer = re.search(r'href=["\'][^"\']*[?&]developer=([^"\'&]*)["\']', window, re.I)
        results.append({
            "title": second[1],
            "publisher": urllib.parse.unquote_plus(developer.group(1)) if developer else "",
            "year": "",
            "url": second[0],
            "source": "Atari Legend",
        })
        if len(results) == 5:
            break
    return results


@lru_cache(maxsize=512)
def lookup_online(query: str, timeout: float = 6.0) -> list[dict]:
    """Search the ST records that answer a plain client, best source first."""
    query = re.sub(r"\s+", " ", query).strip()
    if len(query) < 2:
        return []
    results: list[dict] = []
    identities: set[tuple[str, str]] = set()
    for lookup in (_lookup_atarimania, _lookup_archive_org, _lookup_atari_legend):
        try:
            found = lookup(query, timeout)
        except (OSError, ValueError, urllib.error.URLError, TimeoutError):
            continue
        for item in found:
            identity = (item["title"].casefold(), item["source"])
            if identity not in identities:
                identities.add(identity)
                results.append(item)
        # One unambiguous hit in the reference database is the answer; asking
        # the other two can only add near-duplicates for a person to sort out.
        if lookup is _lookup_atarimania and len(found) == 1:
            return results
    return results[:10]


def enrich_if_ambiguous(metadata: dict) -> dict:
    if not metadata["ambiguous"]:
        return metadata
    query = metadata["title"] or metadata["diskTitle"]
    leaf = str(query or "").rsplit(".", 1)[-1].strip()
    if re.fullmatch(r"(?:\d+|DISC-?\d+|DISK-?\d+|GAMES?\d+|DISCS?\d+)", leaf, re.I):
        metadata["warnings"].append(
            "Online lookup was skipped because the generic directory name "
            "does not identify the software."
        )
        return metadata
    try:
        metadata["matches"] = lookup_online(query)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        metadata["warnings"].append(f"Online lookup was unavailable: {exc}")
        return metadata
    if len(metadata["matches"]) == 1:
        match = metadata["matches"][0]
        metadata["title"] = match["title"]
        metadata["publisher"] = match["publisher"]
        metadata["sources"] = [{"label": match["source"], "url": match["url"]}]
        metadata["confidence"] = min(100, metadata["confidence"] + 15)
    elif metadata["matches"]:
        metadata["warnings"].append("Several online matches were found; choose the correct one.")
    else:
        metadata["warnings"].append("No matching record was found online.")
    return metadata
