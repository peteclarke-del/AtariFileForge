"""Fetching software this application is allowed to fetch.

Two kinds of thing are installed from somebody else's work: hard-disk drivers
and replacement desktops. Both follow the same rule, so both use the same code
to obey it.

The rule is that the licence decides, not how easy the file is to find. Where
the owner has released something, or has plainly abandoned it to a community
that has mirrored it for thirty years, it is fetched. Where it is sold, it is
not, however trivial it would be to go and get a copy. That check is made
against the catalogue rather than against the request, so nothing a caller
sends can ask for something it should not have.

What arrives is written into the directory the operator would have put their
own copy in, so afterwards a download and a copy they supplied are the same
thing and the next install goes nowhere near the network.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from .errors import DiskError

MIB = 1024 * 1024

#: How much of a download is accepted before it is refused. A driver is tens
#: of kilobytes and a desktop a few hundred; anything past this is neither.
MAX_DOWNLOAD_BYTES = 32 * MIB

#: How long to wait for a server that has stopped answering.
DOWNLOAD_TIMEOUT = 120


def fetch_archive(
    label: str,
    sources,
    destination: Path,
    stem: str,
    *,
    accepts=None,
    opener=None,
) -> Path:
    """Download the first source that answers with something usable.

    ``accepts`` is asked whether the archive holds what was wanted. A source
    that answers with a captive portal's login page, or with a perfectly valid
    archive of something else, is refused and not kept, because a file left
    behind here is one the next install would believe in.
    """
    directory = Path(destination)
    directory.mkdir(parents=True, exist_ok=True)
    request_opener = opener or urllib.request.urlopen
    failures: list[str] = []
    for source_label, url in sources:
        try:
            with request_opener(url, timeout=DOWNLOAD_TIMEOUT) as response:
                payload = response.read(MAX_DOWNLOAD_BYTES + 1)
        except (OSError, urllib.error.URLError, ValueError) as exc:
            failures.append(f"{source_label}: {exc}")
            continue
        if len(payload) > MAX_DOWNLOAD_BYTES:
            failures.append(
                f"{source_label}: larger than {MAX_DOWNLOAD_BYTES // MIB} MB"
            )
            continue
        if not zipfile.is_zipfile(io.BytesIO(payload)):
            failures.append(f"{source_label}: what arrived is not a ZIP archive")
            continue
        archive = directory / f"{stem}.zip"
        archive.write_bytes(payload)
        if accepts is not None and not accepts(archive):
            archive.unlink(missing_ok=True)
            failures.append(f"{source_label}: the archive does not hold {label}")
            continue
        return archive
    raise DiskError(
        f"{label} could not be downloaded. "
        + "; ".join(failures)
        + f". Put your own copy in {directory} instead."
    )


__all__ = [
    "DOWNLOAD_TIMEOUT",
    "MAX_DOWNLOAD_BYTES",
    "fetch_archive",
]
