"""Rebuild the generated half of the BASIC test corpus.

Run from the repository root::

    python tests/fixtures/basic/build_fixtures.py

Every file this writes is checked by ``tests/test_atarinut_basic.py``, so a
change to a codec that alters a fixture will fail the tests until the fixture
is rebuilt deliberately and the difference has been looked at.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from atarinut.basic import GFA_BASIC_3, ST_BASIC, detokenise, tokenise  # noqa: E402
from atarinut.basic import stos  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent


def build() -> None:
    gfa_source = (HERE / "tilemap.lst").read_text(encoding="latin-1").rstrip("\n")
    encoded = tokenise(gfa_source, GFA_BASIC_3)
    if detokenise(encoded) != gfa_source:
        raise SystemExit("tilemap.lst no longer round-trips; look before rebuilding.")
    (HERE / "tilemap.gfa").write_bytes(encoded)

    stos_source = (HERE / "stars.asc").read_text(encoding="latin-1").rstrip("\n")
    program = stos.encode_program(stos_source)
    if stos.detokenise_stos(program) != stos_source:
        raise SystemExit("stars.asc no longer round-trips; look before rebuilding.")
    (HERE / "stars.bas").write_bytes(program)

    listing = (HERE / "clock.bas").read_bytes().decode("latin-1").replace("\r\n", "\n")
    (HERE / "clock.bas").write_bytes(tokenise(listing, ST_BASIC))
    print("rebuilt tilemap.gfa, stars.bas and clock.bas")


if __name__ == "__main__":
    build()
