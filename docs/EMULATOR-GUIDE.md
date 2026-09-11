# Emulator guide

Atari File Forge can hand an image to an emulator so a change can be watched
running rather than only inspected. Hatari is the one managed emulator. It
covers every machine from a 520ST to a Falcon030, it takes floppy images,
hard-drive images and host folders, and it is driven entirely from the
command line, which is what makes a test run repeatable on every host.

This guide describes what the application does with Hatari, where it finds
firmware, and what each machine in the hardware catalogue is started with.
The code is `app/emulator_config.py`; the catalogue is
`app/hardware_profiles.py`.

## Finding Hatari

The Docker image installs Debian's `hatari` package. The Linux desktop edition
uses whatever the host has. The executable is looked for in this order:

1. `ATARI_HATARI_EXECUTABLE`, an exact path that wins outright.
2. `ATARI_HATARI_ROOT` (default `/usr/bin`) joined with each packaged name:
   `hatari`, `hatari.hatari` (Snap) and `org.tuxfamily.hatari` (Flatpak
   wrapper).
3. The same names on `PATH`.

A missing executable is reported by the emulator status before anything is
launched. Hatari 2.4 or newer is expected; Debian trixie ships 2.5.

## Finding firmware

Every machine needs a TOS. The lookup is:

1. A real TOS ROM in `ATARI_FILE_FORGE_TOS_DIR` (default
   `~/.config/atari-file-forge/tos`), then in the repository's git-ignored
   `firmware/tos/`, matched by filename. A profile that names a release
   (`tos-104` and its relations) asks for exactly that release; otherwise every
   release the machine shipped with is tried, newest first. The Falcon's
   `tos-4xx` takes the newest of 4.04, 4.02 and 4.00 it finds, and `tos-400`,
   `tos-402` and `tos-404` each ask for that one release. A file that does not
   decode as a ROM, such as a truncated or bad dump, is never offered.
2. The bundled EmuTOS under `firmware/emutos/`: 192 KiB for the ST and Mega
   ST, 256 KiB for the STE and Mega STE, 512 KiB for the TT030 and Falcon030.
   The `tos-emutos` add-on forces this step, and a profile may ask for the
   1024 KiB image with `emulatorFirmware: "emutos-1024k"`.

The status reported to the interface names the ROM chosen and the reason,
for example "TOS 1.04: tos104uk.img was found in ~/.config/atari-file-forge/tos
as the profile requested" or "EmuTOS 256 KiB: etos256uk.img was chosen because
no TOS ROM for the STE was found ... so the bundled EmuTOS boots the machine
instead". The [firmware README](../firmware/README.md) has the filename table
and the redistribution rules.

## The hand-off

`emulator_command(session, media, ...)` returns an argv list and a working
directory. Nothing from a profile or a filename is ever passed through a
shell. The media decides how the machine boots:

| Media | Attached as |
| --- | --- |
| `.st`, `.msa`, `.stx`, `.dim`, `.ipf`, `.hfe`, `.zip` | `--disk-a`; a second disc from an installer run goes in `--disk-b` |
| `.img`, `.hd`, `.ahd`, `.acsi`, `.ide`, `.raw`, `.bin`, `.vhd` | the interface the profile declares (see below) |
| a directory | `--harddrive <dir> --gemdos-drive c`, Hatari's GEMDOS drive |

The machine has two floppy drives, A: and B:, and no more. A CD image can be
attached only on the SCSI machines (TT030 and Falcon030), as a second SCSI
device, because Hatari has no CD-ROM emulation of its own; a CD filing-system
driver on the drive is what reads it.

A hard-drive image is attached to the interface the profile declares:

| Add-on | Hatari option |
| --- | --- |
| `acsi-megafile`, `acsi-third-party`, `acsi2stm`, `ultrasatan`, `cosmosex` | `--acsi 0=<image>` |
| `ide-internal`, `ide-adapter`, `cf-adapter` | `--ide-master <image>` |
| `scsi-internal` | `--scsi 0=<image>` |
| none | the machine's own port: ACSI on the ST family, SCSI on the TT030, IDE on the Falcon |

Every command carries `--fast-boot true` (skip the memory test),
`--confirm-quit false` and `--statusbar false`. Outside a native desktop
window it also carries `--sound off`, because the container has no sound
device and a bounded run has no listener. Screenshots taken inside Hatari land
in the media's directory (`--screenshot-dir`), which is also the working
directory returned to the caller.

### Three ways to run

| Mode | Wrapper | Purpose |
| --- | --- | --- |
| Native interactive | none | The Linux desktop edition opens Hatari in its own window. |
| Managed interactive | `timeout 900 env SDL_AUDIODRIVER=dummy DISPLAY=:99 hatari ...` | The Docker edition shows the shared Xvfb display through noVNC on port 8668. |
| Bounded | `timeout 8 env SDL_AUDIODRIVER=dummy xvfb-run -a hatari ... --run-vbls 350` | A pass-or-fail test run with no display. Hatari leaves after 350 frames (7 seconds), so a normal run exits 0; `timeout` is the backstop. |

The debugger is the bounded or interactive run with `--debug --parse
app/hatari-debugger.txt`, a fixed script that makes CPU exceptions enter
Hatari's debugger with a 512-instruction history and the registers shown. A
debug run allows 15 seconds and 700 frames and logs at `info` level.

The isolated drive sandbox captures two frames from a private display. It
takes the bounded command, replaces `xvfb-run` with its own `DISPLAY`, drops
`--run-vbls` so the machine stays on screen, and lets `timeout` end the run.

### Remote control

Hatari can take commands over a socket. `control_socket_path(work_dir)` names
the socket (`<work_dir>/hatari-control.sock`); a caller that listens on it and
passes `control_socket=` to `emulator_command` gets `--control-socket <path>`
on the command line. Hatari connects to the socket, it does not create it, so
the listener must exist first. The commands are the ones Hatari's own
`hconsole` tool sends (`/usr/share/hatari/hconsole/hconsole.py` in the Debian
package): `hatari-shortcut <name>`, `hatari-option <option>` and
`hatari-debug <command>`, one per line.

## What each machine boots with

| Machine | `--machine` | Default RAM | CPU | Monitor | Extras |
| --- | --- | --- | --- | --- | --- |
| `st` (520ST / 1040ST) | `st` | 512 KiB (`--memsize 0`) | `--cpulevel 0 --cpuclock 8` | `rgb` | `--blitter true` with the `blitter` add-on |
| `megast` (Mega ST 1/2/4) | `megast` | 1 MiB | `--cpulevel 0 --cpuclock 8` | `rgb` | `--blitter true` always |
| `ste` (520STE / 1040STE) | `ste` | 1 MiB | `--cpulevel 0 --cpuclock 8` | `rgb` | |
| `megaste` (Mega STE) | `megaste` | 1 MiB | `--cpulevel 0 --cpuclock 16` | `rgb` | |
| `tt030` (TT030) | `tt` | 2 MiB | `--cpulevel 3 --cpuclock 32` | `vga` | |
| `falcon030` (Falcon030) | `falcon` | 4 MiB | `--cpulevel 3 --cpuclock 16` | `vga` | `--dsp emu` always |

Add-ons change those values:

| Add-on | Effect |
| --- | --- |
| `ram-512k`, `ram-1m`, `ram-2m`, `ram-2.5m`, `ram-4m`, `ram-14m` | `--memsize 0`, `1`, `2`, `2560`, `4`, `14`. Hatari reads 0 as 512 KiB, 1 to 14 as MiB and anything larger as KiB, which is how 2.5 MiB is written. A profile's `emulatorRam` (for example `1M`) overrides the add-on. |
| `tt-ram` | `--ttram 16 --addr24 false`; TT RAM needs the 68030's 32-bit addressing. |
| `acc-68030-pak` | `--cpulevel 3` on an ST-class machine. Only TOS 2.06 and EmuTOS run on it. |
| `fpu-68881`, `fpu-68882` | `--fpu 68881` or `--fpu 68882`. |
| `blitter` | `--blitter true` on a plain ST. |
| `monitor-mono`, `monitor-colour`, `monitor-vga`, `tv-modulator` | `--monitor mono`, `rgb`, `vga`, `tv`. |
| `drive-a-ss` | `--drive-a-heads 1`, the single-sided drive of an early 520ST. |
| `drive-b-external` | Drive B: stays enabled. Without it, and with only one disc, `--drive-b false` is passed so the machine has the drives the profile says it has. |
| storage add-ons | The hard-drive interface, as in the table above. |
| `tos-100` to `tos-4xx`, `tos-400` to `tos-404`, `tos-emutos` | The firmware lookup above. |

Add-ons marked "Validation only" in the interface (Gotek, hard-disk drivers,
ports, loaders) inform compatibility checks and change nothing on the command
line.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `ATARI_HATARI_ROOT` | `/usr/bin` | Directory searched for the Hatari executable. |
| `ATARI_HATARI_EXECUTABLE` | unset | Exact executable to use instead of searching. |
| `ATARI_FILE_FORGE_TOS_DIR` | `~/.config/atari-file-forge/tos` | Where your own TOS ROMs are looked for first. |

## Checking the command yourself

Every `hatari` option used here is listed by `hatari --help`. To see what the
application would run for a profile without starting anything, open the
editor's emulator status: it includes the complete command line, the firmware
chosen and the reason.
