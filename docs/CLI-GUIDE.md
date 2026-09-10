# Headless CLI and deterministic recipes

Atari File Forge includes a supported command-line interface for repeatable
image work, build servers and collection maintenance. It calls the same disk,
validation, manifest, comparison and guarded-patch services as the web
application, so a rule enforced in the browser is enforced here by the same
code. The CLI does not reproduce GEMDOS rules in a separate tool.

The entry point is:

```bash
python -m app.cli --help
```

The complete Docker image carries the conversion tools the commands need. A
source checkout without its Python and native dependencies can print help, but
it cannot open or safely dry-run real images.

## Run it in Docker

Create a host directory for input and output files, then mount it at `/media`:

```bash
mkdir -p media
docker compose run --rm \
  -v "$PWD/media:/media" \
  atari-file-forge \
  python -m app.cli validate /media/game.st
```

This one-off container uses the built application image and leaves the web
service alone. Files written below `/media` appear in the host `media`
directory. Use absolute container paths in recipes and commands.

## Output contract

Progress and human-readable phase messages go to standard error. Standard
output carries one JSON document in this stable envelope:

```json
{
  "format": "atari-file-forge-cli-result",
  "version": 1,
  "command": "validate",
  "status": "ok",
  "exitCode": 0,
  "dryRun": false,
  "result": {}
}
```

The process exit codes are part of the version 1 interface:

| Code | Status | Meaning |
| ---: | --- | --- |
| 0 | `ok` or `planned` | The operation completed, or a dry run completed without writing |
| 2 | `usage-error` | Command syntax or a required argument is wrong |
| 3 | `validation-failed` | The image, the requested operation or a target rule is invalid |
| 4 | `input-error` | A named source, image or patch cannot be found |
| 5 | `identity-mismatch` | A recipe source no longer matches its recorded size or SHA-256 |
| 6 | `operation-failed` | A filing system, conversion or host I/O operation failed |

Argument errors use the same JSON envelope on standard output and put the
short usage line on standard error. Scripts should test the numeric exit code,
then inspect `status`, `result.error` and `result.errorType`.

## Opening an image

Every command that takes an image accepts two shared options.

`--target-hardware` states what the image is for, which decides the rules
applied when it is finalised. It accepts `auto`, `floppy`, `hd`, `volume` and
`tos`, and defaults to `auto`.

`--force-kind rom` opens a file as a raw ROM rather than letting its contents
decide. Use it for a ROM dump whose size or header does not identify it.

A hard disk is one file with a partition table inside it, so a command that
works on a volume inside a drive names the partition with `--partition`.

## Commands

### Create an image

```bash
python -m app.cli create --format ds-720k --title WORK --output /media/work.st
```

`--format` accepts the same identifiers as the web creation service.

| Group | Identifiers |
| --- | --- |
| Single-sided floppies | `ss-360k`, `ss-400k`, `ss-440k` |
| Double-sided floppies | `ds-720k`, `ds-800k`, `ds-880k`, each also in `-81`, `-82` and `-83` track variants |
| High density | `hd-1440k` |
| HFE track images | `hfe-st-360k`, `hfe-st-720k`, `hfe-st-800k`, `hfe-st-880k`, `hfe-st-1440k` |
| Hard disks and volumes | `hd`, `volume` |
| ROM images | `rom`, `cartridge` |

`--capacity` is required only for formats whose size is genuinely selectable,
which means `hd` and `volume`. The ROM formats also accept `--bank-size`,
`--total-size`, `--platform` (`tos`, `cartridge` or `custom`), `--layout` and
`--template`.

The extended track counts exist because an ST drive will step past eighty
cylinders and a great deal of commercial and public-domain software shipped on
eighty-one to eighty-three track disks to gain the extra space. A real drive
may refuse the highest of them, so test before committing a collection to one.

### Finalise and save an existing image

```bash
python -m app.cli save /media/drive.hd \
  --target-hardware hd \
  --output /media/drive-ready.hd
```

Save runs the hardware finalisation path before copying bytes. HFE output is
re-encoded and verified when the source was opened as an editable HFE. An
existing output is rejected unless `--force` is explicit.

### Inspect and validate

```bash
python -m app.cli manifest /media/collection.hd \
  --output /media/collection-manifest.json

python -m app.cli validate /media/collection.hd --partition 1
```

The manifest holds directory records, GEMDOS metadata and hashes, plus the
deterministic logical fingerprint that recipes and patches check. A hard disk
can be validated one partition at a time. Omit `--partition` to validate the
whole container, including its partition table.

Build the same versioned compatibility report the browser shows, from a JSON
array of proposed changes:

```bash
python -m app.cli preflight /media/work.st \
  --changes /media/proposed-changes.json \
  --source-kind volume --target-kind floppy \
  --operation copy \
  --output /media/compatibility-report.json
```

Each proposed row may carry a name, a source, a type, an attribute string and
a datestamp. The report records per-item conversions and losses, blocking
findings, the target profile and `canProceed`. It is the place where an
eight-character truncation, a changed extension, a name collision or a
datestamp outside the FAT range is reported before anything is written.
`import-file --dry-run` embeds the same report under `result.compatibility`.

### Import one host file

```bash
python -m app.cli import-file /media/work.st /media/PROGRAM.PRG \
  --destination GAMES/PROGRAM.PRG \
  --attributes 'r----a' \
  --output /media/work-with-program.st
```

Use `--partition` for a volume inside a hard disk. `--attributes` accepts
either form: the six letters printed in the catalogue, such as `-----a` or
`r----a`, or the raw byte in hexadecimal, written `01`, `$01` or `0x01`. The
letters stand for read-only, hidden, system, volume label, directory and
archive, in that order, and a letter shown means the bit is set. There is no
inversion anywhere, which is the opposite of some other machines of the
period.

There is deliberately no comment option and no load or execution address.
GEMDOS records none of them. A program carries its own header giving the text,
data and uninitialised sizes, and the loader reads that. The
[file metadata guide](FILE-METADATA-GUIDE.md) sets out what a directory entry
can and cannot hold.

Filename, folder and metadata rules belong to the destination filing system
service, so a name too long for GEMDOS is refused here exactly as it is in the
browser.

### Rebuild the disk a container describes

```bash
python -m app.cli convert-container /media/game.msa \
  --format st --output /media/game.st
```

This command deliberately means container to sector image. It does not claim a
general conversion between arbitrary formats. `--format` accepts `st`, `msa`
and `dim`, and the source may be any of those three or a Pasti capture. Every
track is written back at the cylinder it came from, so the output is the disk
the container was made from, exactly as in the browser. A track this build
cannot decode stops the conversion rather than producing a disk with a hole in
it.

A Pasti capture converts one way only. It records a physical read including
the parts a normal controller cannot reproduce, so it is opened read-only and
converts to a sector image only where its tracks are ordinary.

### Compact a volume

```bash
python -m app.cli compact /media/work.st --output /media/work-compact.st
```

FAT allows a file's clusters to lie anywhere on the disk, and a volume written
and deleted over time ends up with files threaded through each other. That
costs a real machine a seek on every read. Compaction rewrites the volume with
each file's clusters consecutive. A hard disk is compacted one partition at a
time with `--partition`. A ROM image is already rebuilt into storage order
after every edit, and a read-only container has no compaction operation, so
both are refused.

### Compare images and create patches

```bash
python -m app.cli compare /media/before.st /media/after.st \
  --output /media/comparison.json

python -m app.cli patch-create /media/before.st /media/after.st \
  --output /media/change.affpatch.zip

python -m app.cli patch-apply /media/before.st /media/change.affpatch.zip \
  --output /media/patched.st
```

Comparison uses logical records and exact fingerprints, so a disk rewritten
with the same files in a different cluster order compares as unchanged. Patch
creation includes only the payloads it needs. Patch application verifies the
base fingerprint, the physical layout, the canonical operation plan and every
payload before writing anything, then checks the complete candidate
fingerprint afterwards.

## Dry run

Add `--dry-run` to any mutating command. No output image or patch is created,
`status` is `planned`, `dryRun` is true, and `result` holds the resolved source
identity, the decisions and the intended output.

A dry run is not a description. It opens a private disposable copy, performs
the real requested mutation there and then discards it. That catches capacity,
directory and format errors a plan alone would miss. Patch application performs
the complete guarded preflight, payload hashes included, without applying it.

## Versioned recipes

`create`, `save`, `import-file`, `convert-container` and `compact` accept
`--recipe-out`. After a successful operation the file records:

- the recipe format and version;
- the exact physical size and SHA-256 of every input;
- the image's logical fingerprint, where an image was opened;
- every non-secret decision the action made;
- the target-hardware and raw-ROM interpretation choices used to open inputs;
- the chosen output, and hashes of the files it generated.

Run a recipe by mapping each source alias to a current path:

```bash
python -m app.cli recipe-run /media/import.affrecipe.json \
  --source image=/media/original.st \
  --source payload=/media/PROGRAM.PRG \
  --output /media/rebuilt.st
```

The rebuild stops with exit code 5 if an input's bytes have changed. The open
image's logical fingerprint is checked as a second guard. Paths are supplied at
run time so a recipe can move between computers without weakening its identity
checks. Session identifiers, credentials and private working paths are never
stored as execution authority.

After the rebuild, every generated file is checked against the size and
SHA-256 the completed workflow recorded. A mismatch also returns exit code 5,
rather than being reported as a successful deterministic rebuild.

Version 1 recipes execute create, import-file, compact, container conversion,
guarded patch application and the final save decision. A recipe produced by a
newer version of the application is rejected until its schema is supported,
rather than guessed at.

### Export a completed workflow from the interface

Open **Workbench**, choose **Portable project**, select an open image and
export the workflow bundle. The downloaded `.affrecipe.zip` holds:

- `workflow.affrecipe.json`, the versioned recipe with every expected output
  hash;
- `changes.affpatch.zip`, the guarded logical changes from the earliest
  retained pre-change checkpoint to the current image;
- `README.md`, the exact base identity and a ready-to-edit replay command.

The original image is deliberately not copied into the bundle, because the
bundle is a record of what was done rather than a second copy of your
collection. Extract it, then map `image` to the recorded base and `changes` to
the bundled patch:

```bash
python -m app.cli recipe-run workflow.affrecipe.json \
  --source image=/media/original.st \
  --source changes=changes.affpatch.zip \
  --output rebuilt.st
```

Replay verifies both physical input hashes, the base logical fingerprint, the
patch payloads and the final output hashes. The recipe keeps the chosen
hardware profile, the target validation and the accepted compatibility reports
as descriptive decisions, but never browser ownership tokens or private server
paths.

An edited session with no retained pre-change checkpoint is rejected rather
than exported as a false reconstruction. Save it, create a named checkpoint and
use that as the base for later recorded changes.

Two kinds of image cannot be exported this way yet. An MSA, DIM or Pasti
container is read-only, so convert one to a sector image first. An HFE
workflow is refused because replay would have to preserve the original track
container as well as the decoded filing system, and that has not been proved
lossless.

HFE work uses the same bundled HxCFloppyEmulator converter (`hxcfe`) as the
graphical application. Docker and native release packages carry the executable
and its libraries. See the [HFE, SCP and HxCFE guide](HFE-HXC-GUIDE.md) for the
supported layouts and for the encode, decode and byte-comparison save gate.

## Safety notes

- Inputs are copied into an isolated temporary work directory. The source file
  is never edited in place.
- Mutating commands require a separate output and refuse an existing file
  unless `--force` is given.
- The CLI does not bypass the read-only container, protected HFE, composite
  ROM or incomplete geometry rules.
- Keep the JSON result with your build logs. It records the exact failure
  category even where a conversion tool also writes diagnostics to standard
  error.
