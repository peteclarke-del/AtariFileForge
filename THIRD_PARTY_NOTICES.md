# Third-party notices

Atari File Forge source is distributed under the MIT License in
[LICENSE](LICENSE). The application also uses software, system packages and
firmware governed by separate terms. This inventory records the dependency
boundary; it does not replace the authoritative licence text supplied by each
copyright holder.

## Python and browser dependencies

| Component | Version in this repository | Licence | Project |
| --- | --- | --- | --- |
| Flask | 3.1.3 | BSD-3-Clause | <https://github.com/pallets/flask> |
| Gunicorn | 26.2.0 | MIT | <https://github.com/benoitc/gunicorn> |
| Capstone | 5.0.9 | BSD-3-Clause | <https://github.com/capstone-engine/capstone> |
| Playwright | 1.63.0, development and browser tests | Apache-2.0 | <https://github.com/microsoft/playwright> |

The GEMDOS filing-system engine in `atarinut/` is part of this project, not a
third-party dependency. It is covered by the same MIT licence as the rest of
the source and has no dependencies of its own beyond the Python standard
library.

**No Atari TOS is included.** TOS ROMs and TOS boot disks remain the
copyright of Atari's successors, are not redistributable, and are neither
shipped nor downloaded by any build step. The emulator hand-off reads TOS ROMs
the user supplies, and otherwise boots the bundled EmuTOS, which is free
software (see below).

Transitive Python and Node packages retain their own terms. The authoritative
installed inventory is produced by `python -m pip list` and `npm ls`; package
metadata and licence files should be retained by a binary distributor.

The native Debian package vendors the pinned Python dependency set under
`/opt/atari-file-forge/vendor`. GTK, Libadwaita, WebKitGTK, PyGObject and
desktop integration tools remain distribution packages and keep their system
copyright records. The package builder excludes the repository firmware tree,
samples, working images and Git metadata.

## Source-built and runtime tools

| Component | Pinned revision or source | Licence boundary |
| --- | --- | --- |
| HxC Floppy Emulator command-line engine | `b1eee4cd73391ceaf2ad4ac57e28bf11c91333ba` | GPL-3.0; the Linux package installs the upstream `COPYING` file under `native/share/licenses` |
| Hatari | Debian runtime package (2.4 or newer; trixie ships 2.5.0) | GPL-2.0-or-later; the only emulator this project bundles. Atari TOS ROMs are separate and are not shipped. |
| EmuTOS | 1.4, `firmware/emutos/` (`etos192uk`, `etos192us`, `etos256uk`, `etos256us`, `etos512uk`, `etos512us`, `etos1024k`) | GPL-2.0-or-later; the licence text is committed beside the images as `firmware/emutos/LICENSE.txt`, and the source is at <https://github.com/emutos/emutos>. Checksums are in [firmware/README.md](firmware/README.md). |
| noVNC | Debian runtime package | MPL-2.0 for the core library, with separately licensed web assets |
| websockify | Debian runtime package | LGPL-3.0 |
| Greaseweazle | Optional host tool | GPL-3.0; not copied into the application repository |

The Docker build also installs Debian libraries and utilities, including GTK
and Libadwaita integration dependencies, Xvfb, x11vnc, ImageMagick and
xdotool. Their exact versions are selected by the pinned Debian
base distribution and retain the copyright files installed under
`/usr/share/doc`. Distributing a container image may trigger notice or source
obligations beyond those of the Atari File Forge source repository.

## Firmware and ROM material

Files under `firmware/` are not covered by the Atari File Forge MIT licence.
The only firmware shipped there is EmuTOS, under the GPL recorded above. No
Atari TOS is shipped; the directory records what a user may supply themselves
and where the application looks for it. Its purpose and update rules are in
[firmware/README.md](firmware/README.md).

The repository currently documents that redistribution rights must be
confirmed before publishing a derived source archive, container image or
native package. A distributor must not infer permission from the presence of a
binary in this repository. Replace or omit material whose redistribution basis
cannot be established.

ROMs, disk images, archives and hard-drive images opened or downloaded
by a user retain the rights of their original authors and publishers. Atari
File Forge does not relicense them.

## Maintaining this inventory

A dependency update must record the new version or commit, upstream source,
licence, required notices and any source-offer obligation. Firmware updates
also require provenance, redistribution review and SHA-256 verification. The
release checklist treats those records as a release gate.
