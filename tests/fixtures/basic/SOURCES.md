# BASIC test corpus

Six files. Four are generated here so the tests own every byte in them; two
come from public repositories so that the readers are exercised against source
a real Atari ST wrote rather than only against their own output.

Regenerate the four generated files with:

    python tests/fixtures/basic/build_fixtures.py

## Generated for this repository

| File | Dialect | What it exercises |
| --- | --- | --- |
| `tilemap.lst` | GFA BASIC 3 | The listing form: `PROCEDURE`/`RETURN`, `FUNCTION`/`ENDFUNC`, `IF`/`ELSE`/`ENDIF`, nested `FOR`/`NEXT`, `WHILE`/`WEND`, `REPEAT`/`UNTIL`, `DO`/`EXIT IF`/`LOOP`, `SELECT`/`CASE`/`DEFAULT`/`ENDSELECT`, typed names, arrays and string expressions. |
| `tilemap.gfa` | GFA BASIC 3 | `tilemap.lst` put through `tokenise`. The tests prove it lists back to exactly that text and re-encodes to exactly these bytes. |
| `stars.asc` | STOS BASIC | The listing form: integer, hexadecimal and float literals, string and float variables, arrays, `repeat`/`until`, `for`/`next`, `if`/`then`, `rem`. |
| `stars.bas` | STOS BASIC | `stars.asc` put through the STOS writer. See `atarinut/basic/stos.py` for why that writer is for this corpus and not for a real STOS. |
| `clock.bas` | Atari ST BASIC | A numbered ASCII listing using the window, drawing, sound and error-handling words that make ST BASIC recognisable. |

`clock.bas` is stored with the ST's CR LF line endings, because that is what
ST BASIC writes and what the identity round trip has to preserve.

## Fetched from public repositories

| File | Origin | Licence |
| --- | --- | --- |
| `gfademo.lst` | `demo/GFADEMO.LST` from <https://github.com/sandord/ikbd4gfa> | CC0-1.0 (<https://github.com/sandord/ikbd4gfa/blob/main/LICENSE>) |

The file is unmodified, including its CR line endings.

## Why there is no real-world STOS sample

There are public repositories of STOS source, and the STOS reader in this
package was in fact derived from one of them: `mw333/stos-amos-90s`, which
ships 35 programs as both the tokenised `.BAS` and the `.ASC` listing STOS
itself wrote. Those pairs are what recovered the keyword table in
`atarinut/basic/stos_tables.py`, and the reader lists 93% of their lines
identically to STOS's own export.

None of them is under any licence, so none is redistributed here. The STOS
tests therefore run against `stars.bas`, which this repository generates. That
is a real gap and it is worth stating plainly: it means the committed tests
cover the STOS reader's framing and literals, but not a byte stream a genuine
STOS wrote. If a freely licensed `.BAS` turns up, add it here.
