# Release checklist

This checklist defines the release gate for Atari File Forge. It is
version-neutral so it remains valid for every candidate and final release. The
gate must be reproducible from a clean checkout without anything in `samples/`.

Return to the [documentation index](README.md) for the operator and technical
handbooks validated by this gate.

The evidence for the automated rows below is the CI run on the commit being
released. Every push runs the complete Python suite inside the application
image, the JavaScript unit tests, the six browser regressions against a live
container, the amd64, arm64 and ARMv7 image builds, and the Debian 13 and
Ubuntu 24.04 native packages for all three architectures. Link that run from
the release notes; it is reproducible and tied to the exact commit, which a
transcribed local record is not.

CI does not satisfy the physical-hardware rows. Those still need a real
machine, and no automated result should be read as covering them.

Record the intended version before starting:

```bash
export RELEASE_VERSION=0.0.0
test "$(cat VERSION)" = "$RELEASE_VERSION"
```

Use the real release value. Do not copy the example unchanged.

## 1. Source and scope

- [ ] The release branch contains only reviewed, intentional changes.
- [ ] `git status --short` is empty before the final build.
- [ ] `VERSION`, the API health response, generated archive README and planned
      Git tag all report the same version.
- [ ] No secrets, personal paths, commercial media or local firmware sources
      have entered the change.
- [ ] `samples/`, `output/`, browser downloads, working sessions and benchmark
      scratch data are absent from the commit and `git archive` output.
- [ ] Dependency and firmware changes include provenance, version, licence and
      checksum review.
- [ ] `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, `SECURITY.md` and the
      dependency inventory agree with the release contents.
- [ ] Firmware redistribution rights have been established for every binary
      retained in the source archive or published image. Unresolved material is
      omitted rather than assumed to be covered by the project licence.
- [ ] Any format restriction or repair behaviour changed by the release is
      called out in the release notes.
- [ ] `tools/build-release.sh` creates a source archive, native `.deb` and
      `SHA256SUMS` from the clean tagged tree.
- [ ] `.github/workflows/release.yml` builds Debian 13 and Ubuntu 24.04
      packages for AMD64, ARM64 and ARMv7, inspects their metadata and imports
      their vendored native dependencies before publication.

## 2. Documentation

- [ ] [README.md](../README.md) describes the current formats, UI and limits.
- [ ] [Installation](INSTALLATION.md) matches the Dockerfile, Compose service,
      ports, volume and all supported host architectures.
- [ ] [File editor guide](FILE-EDITOR-GUIDE.md) matches editor menus, save
      semantics, analysis, emulators and read-only cases.
- [ ] [ROM guide](ROM-GUIDE.md) matches TOS ROM, cartridge, Workbench and programmer
      behaviour.
- [ ] In-app Help uses the same menu names and workflow decisions.
- [ ] Firmware notes contain current checksums and runtime paths.
- [ ] Every local Markdown link and image reference resolves.
- [ ] Screenshots of changed interfaces come from the release build, use no
      private media and remain readable at their rendered size.
- [ ] Documentation contains no obsolete project name, stale hardcoded release
      command or unsupported claim.

## 3. Automated build matrix

Build and test these native targets:

| Platform | Typical system | Required result |
| --- | --- | --- |
| `linux/amd64` | x86-64 Linux or Docker Desktop | Image builds, native runtime gate and complete tests pass |
| `linux/arm64` | 64-bit Raspberry Pi OS or Apple Silicon builder | Image builds, native runtime gate and service health pass |
| `linux/arm/v7` | 32-bit Raspberry Pi OS | Image builds, native runtime gate and service health pass |

For each target:

- [ ] Docker builds from a clean enough cache to exercise changed dependency
      stages.
- [ ] Native Capstone exposes M68K support for every 68000-family mode.
- [ ] HxC converter and emulator stages complete.
- [ ] Runtime package names resolve on the selected Debian base.
- [ ] Every Python test passes inside the primary AMD64 test image.
- [ ] `node tests/run_js_tests.js` passes in the primary test job.
- [ ] Each architecture imports Atarinut and Flask, creates the application,
      exercises all required Capstone engines and contains the native HxC
      and emulator executables.
- [ ] The service starts on port `8666` and the health endpoint reports the
      expected version.
- [ ] `npm run test:browser` passes against the primary built service.
- [ ] A generated BASIC file and a generated machine-code file produce bounded,
      read-only cheat-candidate reports; plain text is rejected explicitly.
- [ ] Guarded cheat preparation refuses BASIC and archive members, changing
      source hashes, mismatched original bytes and fewer than two distinct
      tester-supplied emulator observations. A valid apply creates a checkpoint,
      while the private library matches the exact file hash and original bytes.
- [ ] `git diff --check` passes.
- [ ] The native `.deb` builds on each claimed Debian or Ubuntu target, passes
      `dpkg-deb --info` and `dpkg-deb --contents`, and contains no firmware,
      samples, working images or Git metadata.
- [ ] A clean test machine installs the `.deb` with APT, shows the desktop
      entry and MIME associations, launches the GTK host, saves an image, then
      upgrades and removes the package without deleting XDG user state.

When a build fails, retain the first Docker `ERROR` block. Later `CANCELED`
stages are usually consequences of that failure.

## 4. Generated-media and fault gate

The generated-media test matrix must create and reopen:

- [ ] ST sector images at 360K, 720K, 800K and 880K;
- [ ] a 1.44M high-density image;
- [ ] a bare GEMDOS volume image;
- [ ] a hard-disk image with a partition table and several partitions;
- [ ] a byte-swapped drive image;
- [ ] an IPF capture, skipped cleanly when the SPS decoder library is absent;
- [ ] MSA and DIM containers, one of each with one deliberately
      ambiguous read-only recording;
- [ ] clean writable HFE v1 and guarded read-only HFE variants;
- [ ] raw and banked ROM images;
- [ ] a cartridge ROM image;
- [ ] supported raw GEMDOS layouts.

Writable filesystems must write, rename, lock, move, delete, compact, save and
reread known data. Cross-format tests must cover valid metadata conversion,
filename replacement, free-block capacity, empty disks, several partitions and
cancelled batch work.

Fault tests must cover:

- [ ] interrupted upload;
- [ ] exact checkpoint rollback after a partial write;
- [ ] a full data area and a full root directory;
- [ ] corrupt boot sectors and broken chains;
- [ ] a partition table whose entries fall outside the image;
- [ ] cancellation at every safe cancellation boundary;
- [ ] browser ownership isolation;
- [ ] simulated container restart with retained sessions;
- [ ] failed save packaging without loss of the working image;
- [ ] stale online catalogue result and partial network failure.

## 5. Browser and interface gate

- [ ] Start with one pane, add more than three, move, resize, overlap, snap,
      minimise, restore and close panes.
- [ ] Refresh restores open images, paths, selections and every pane's window
      geometry, snap, stack and minimised state.
- [ ] Long open, copy, analysis and save operations show phase, item
      count, elapsed time, throughput, ETA and Abort when safe.
- [ ] Creative and destructive controls disable while their operation runs.
- [ ] Errors appear above the active editor or workflow dialog and remain
      actionable.
- [ ] Menus close after an item is selected, on outside click, and when moving
      to another open top-level menu.
- [ ] Light and dark themes work at desktop and narrow widths, 200 percent zoom
      and reduced motion.
- [ ] Keyboard focus, labels, live regions, dialog trapping and non-colour state
      cues satisfy the documented WCAG 2.2 AA target.
- [ ] Save downloads do not announce completion until the ZIP is genuinely
      available to the browser.
- [ ] The platform-contract tests report no undeclared web or desktop route
      differences and both hosts serve the same static frontend.
- [ ] On Linux, the GTK host starts without Docker, opens multiple associated
      image files from both the native chooser and file manager,
      recovers its XDG sessions and saves a complete package to Downloads.
- [ ] A managed emulator opens in a native window from the Linux host, closes
      with the application, and still uses noVNC when launched from Docker.

## 6. Format and workflow gate

Manually verify at least one representative image for each changed family.
For a broad release, cover all of these:

- [ ] Folders, metadata, file operations and image creation on FAT12 and FAT16.
- [ ] File-level Attributes and Modified columns show the values the
      volume actually holds. Attributes read as the six `rhsvda` letters
      `List` prints, with the four low bits shown as permissions rather than as
      the inverted raw bits.
- [ ] Editing the attributes or the datestamp changes the directory entry without
      changing file bytes and creates an undo point.
- [ ] Partition table listing, multi-selection, Cut/Copy/Paste, access,
      duplicate detection and individual partition download.
- [ ] Folder traversal, same-image move, installed-software audit and large
      drive save.
- [ ] HFE capability detection and guarded save.
- [ ] Container hierarchy, structural rebuild, read-only ambiguity gate
      and extraction into writable media.
- [ ] ROM banking, entry-point and help discovery, Workbench, compare, build,
      programmer export and project persistence.
- [ ] Cartridge ROM create, edit, capacity handling and save.
- [ ] ZIP and archive hierarchy, member preview and editor hand-off.
- [ ] Online Library machine default, sorting, already-present filtering,
      multi-selection and installation.
- [ ] Private collection persistence in web IndexedDB and desktop XDG state,
      stale revision handling, cross-image reports and bounded backup merge,
      replacement and clearing.
- [ ] Launcher detection priority, launch action and STACK derivation, with an
      ambiguous disk marked rather than guessed.
- [ ] Headless CLI create, save, validate, preflight, import, compare and patch
      commands return the versioned JSON envelope and documented exit codes.
- [ ] CLI dry-run writes no output, deterministic recipes reject changed
      inputs, and accepted compatibility reports appear in saved ZIPs.
- [ ] Cross-format drag, clipboard, File-menu and Online Library batches show
      the shared compatibility report before their first destination write.
- [ ] Gotek, SD card, CF card, host folder and ACSI deployment plans list exact
      paths and hashes, reject stale revisions and produce a ZIP whose manifest
      matches every payload. Confirm planning leaves the live image unchanged.

## 7. Editor and emulator gate

- [ ] Tokenised BASIC opens with correct line spacing and saves valid tokens.
- [ ] Scripts, plain text, archives, binary files and unknown data select the
      documented editor or hex fallback.
- [ ] Search and replace, undo/redo, save, save as and local export work.
- [ ] Tooltips distinguish ST BASIC statements from GEMDOS commands and
      decode library vectors, custom-chip registers and ST BASIC statements
      in the active hardware context.
- [ ] Formatting is presentation-only. Refactor and condense are guarded,
      reversible edits and do not renumber before acceptance.
- [ ] Disassembly headers align with rows, code/data regions persist, strings
      navigate correctly and annotations identify known calls.
- [ ] Emulator options match the selected profile and mounted media
      capabilities.
- [ ] noVNC on port `8668` displays the launched emulator and errors are visible
      above the invoking editor or pane.
- [ ] A profile that declares a mass-storage interface attaches a private copy
      of the working drive image to the emulator and boots from it, while a profile
      without one says so plainly instead of attaching a drive.

## 8. Performance record

Run the quick profile during development and the full profile before tagging:

```bash
python -m tools.benchmark_media --profile quick --output output/benchmark-quick.json
python -m tools.benchmark_media --profile full --output output/benchmark-full.json
```

The full record must include minimum, median and maximum duration for:

- listing every partition of a hard drive;
- listing a populated root directory;
- browsing a generated folder tree;
- bulk import into a hard-disk partition;
- browsing and checkpointing a whole drive image;
- validating, documenting and building the complete drive save ZIP.

Keep the full JSON as a CI or release artefact. Compare medians with the previous
candidate and explain or fix a material regression.

## 9. Real-hardware gate

For a tagged release, use downloads produced by that exact build:

- [ ] an edited floppy image on a real ST or STE, written with a Greaseweazle
      or read from a Gotek;
- [ ] an edited single-sided disk on a machine with a single-sided drive;
- [ ] a prepared hard-disk image on the ACSI or IDE interface it was built for,
      booted with the driver the plan named or driverless under EmuTOS;
- [ ] a partition at each size the selected TOS release can mount, and one
      deliberately beyond it to confirm the warning was right;
- [ ] a byte-swapped IDE image written to a CF card and read back;
- [ ] at least one TT030 or Falcon030 image when that code changed.

Confirm directory changes, attributes, datestamps and the boot sector after
a cold restart, not only in an emulator.

## 10. Saved-package gate

Every tested **Save image** download must contain:

- [ ] a timestamped, collision-resistant ZIP name;
- [ ] the image under its intended user-facing name;
- [ ] partner metadata files where applicable;
- [ ] individual file exports carry the real GEMDOS path, attributes,
      datestamp and length;
- [ ] generated technical `README.md` with version, profile, catalogue,
      warnings, checksums and usage notes;
- [ ] `ROM-project.json` for ROM projects;
- [ ] no temporary, session, source-path or private browser data.

Reopen the contents of at least one ZIP from each writable media family.

## 11. Tagging and publication

Merge the reviewed release pull request first. Tag the exact merge commit on
`main`:

```bash
git switch main
git pull --ff-only
test "$(cat VERSION)" = "$RELEASE_VERSION"
git tag -a "v$RELEASE_VERSION" -m "Atari File Forge $RELEASE_VERSION"
git push origin "v$RELEASE_VERSION"
```

Do not tag a feature-branch head. GitHub may create a different merge commit,
and the release tag must identify the code users actually clone.

Pushing the tag starts the release workflow. It validates the tag against
`VERSION`, builds the source archive and six distribution-specific packages,
creates `SHA256SUMS`, and publishes the GitHub Release only after every package
gate succeeds.

Finally:

- [ ] create the GitHub Release from that tag;
- [ ] attach benchmark and other intended release artefacts;
- [ ] publish human release notes with known restrictions and upgrade advice;
- [ ] verify the public HTTPS clone and clean Compose build instructions;
- [ ] keep the previous known-good release available for rollback.
