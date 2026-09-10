window.AtariCallCatalogue = (() => {
  // An Atari ST program reaches TOS through the 68000 TRAP instruction. The
  // function number is pushed as a word and the arguments follow it on the
  // stack: TRAP #1 is GEMDOS, TRAP #13 the BIOS and TRAP #14 the XBIOS. GEM
  // is reached through TRAP #2 with D0 selecting the AES ($C8) or the VDI
  // ($73) and D1 pointing at the parameter block. The Line-A opcodes are
  // illegal instructions the ROM traps as a fast path into the VDI's own
  // drawing primitives. This catalogue turns those numbers, and the values
  // around them, into readable explanations for the editor and disassembler.

  const DEFAULT_MACHINES = Object.freeze(["st", "megast", "ste", "megaste", "tt030", "falcon030"]);
  const STE_AND_LATER = Object.freeze(["ste", "megaste", "tt030", "falcon030"]);
  const BLITTER_MACHINES = Object.freeze(["megast", "ste", "megaste", "tt030", "falcon030"]);
  const EXTRA_SERIAL_MACHINES = Object.freeze(["megaste", "tt030", "falcon030"]);
  const TT_AND_FALCON = Object.freeze(["tt030", "falcon030"]);
  const TT_ONLY = Object.freeze(["tt030"]);
  const FALCON_ONLY = Object.freeze(["falcon030"]);

  // ---------------------------------------------------------------- values

  const FOPEN_MODES = Object.freeze({
    0: "read only",
    1: "write only",
    2: "read and write",
  });

  const FSEEK_MODES = Object.freeze({
    0: "from the start of the file",
    1: "from the current position",
    2: "from the end of the file",
  });

  const ATTRIBUTE_BITS = Object.freeze([
    { mask: 0x01, name: "read-only", set: "read-only", clear: "" },
    { mask: 0x02, name: "hidden", set: "hidden", clear: "" },
    { mask: 0x04, name: "system", set: "system", clear: "" },
    { mask: 0x08, name: "volume label", set: "volume label", clear: "" },
    { mask: 0x10, name: "subdirectory", set: "subdirectory", clear: "" },
    { mask: 0x20, name: "archive", set: "archive bit set", clear: "" },
  ]);

  const PEXEC_MODES = Object.freeze({
    0: "load and go: load the program, run it and return its exit code",
    3: "load: load the program and return its basepage without running it",
    4: "go: run a program whose basepage was returned by mode 3",
    5: "create basepage: allocate a basepage and environment for a program loaded by hand",
    6: "go and free: run a loaded program and release its memory when it ends (TOS 1.04 or later)",
    7: "create basepage with TT RAM flags: as mode 5, honouring the program flags (TOS 3.00 or later)",
  });

  const GETREZ_VALUES = Object.freeze({
    0: "ST low, 320x200 in 16 colours",
    1: "ST medium, 640x200 in 4 colours",
    2: "ST high, 640x400 monochrome",
    4: "TT medium, 640x480 in 16 colours",
    6: "TT high, 1280x960 monochrome",
    7: "TT low, 320x480 in 256 colours",
  });

  const RWABS_FLAGS = Object.freeze([
    { mask: 0x01, set: "write", clear: "read" },
    { mask: 0x02, set: "do not update the media-change state", clear: "update the media-change state" },
    { mask: 0x04, set: "ignore a media change and do not retry", clear: "honour a media change" },
    { mask: 0x08, set: "physical mode: the sector number is a physical sector (AHDI 3 or later)", clear: "logical sectors" },
  ]);

  const SUPER_ARGUMENTS = Object.freeze({
    0: "switch to supervisor mode, keeping the current stack; the old supervisor stack pointer is returned in D0",
    1: "query only: D0 returns 0 in user mode and -1 in supervisor mode",
  });

  const BCONOUT_DEVICES = Object.freeze({
    0: "PRT, the Centronics printer port",
    1: "AUX, the RS-232 serial port",
    2: "CON, the console with VT52 interpretation",
    3: "MIDI, the MIDI ports",
    4: "IKBD, the intelligent keyboard controller",
    5: "raw console, the screen without VT52 interpretation",
    6: "ST compatible serial port (Modem 1) on a TT or Falcon",
    7: "SCC channel B (Modem 2) on a Mega STE, TT or Falcon",
    8: "TT MFP serial port (Serial 1)",
    9: "SCC channel A (Serial 2 or the LAN port)",
  });

  const MEDIACH_RESULTS = Object.freeze({
    0: "the medium has definitely not changed",
    1: "the medium may have changed",
    2: "the medium has definitely changed",
  });

  const FORM_ALERT_ICONS = Object.freeze({
    0: "no icon",
    1: "an exclamation mark (NOTE)",
    2: "a question mark (WAIT)",
    3: "a stop sign (STOP)",
    4: "an information icon (AES 4.1 or later)",
    5: "a disk icon (AES 4.1 or later)",
  });

  const EVNT_MULTI_FLAGS = Object.freeze([
    { mask: 0x01, set: "MU_KEYBD, a key press", clear: "" },
    { mask: 0x02, set: "MU_BUTTON, a mouse button change", clear: "" },
    { mask: 0x04, set: "MU_M1, the mouse entering or leaving rectangle 1", clear: "" },
    { mask: 0x08, set: "MU_M2, the mouse entering or leaving rectangle 2", clear: "" },
    { mask: 0x10, set: "MU_MESAG, a message in the application's pipe", clear: "" },
    { mask: 0x20, set: "MU_TIMER, the timer elapsing", clear: "" },
    { mask: 0x40, set: "MU_WHEEL, a mouse wheel movement (XaAES and MyAES)", clear: "" },
    { mask: 0x80, set: "MU_MX, any mouse movement (MagiC)", clear: "" },
  ]);

  const AES_OBJECT_TYPES = Object.freeze({
    20: "G_BOX, a box with a border and fill",
    21: "G_TEXT, text with a TEDINFO",
    22: "G_BOXTEXT, a box containing TEDINFO text",
    23: "G_IMAGE, a monochrome bit image",
    24: "G_USERDEF, an application-drawn object",
    25: "G_IBOX, an invisible box",
    26: "G_BUTTON, a text button",
    27: "G_BOXCHAR, a box containing one character",
    28: "G_STRING, a plain string",
    29: "G_FTEXT, editable formatted text",
    30: "G_FBOXTEXT, an editable formatted text box",
    31: "G_ICON, a monochrome icon",
    32: "G_TITLE, a menu title",
    33: "G_CICON, a colour icon (AES 3.3 or later)",
    34: "G_SWBUTTON, a cycling button (AES 4.1)",
    35: "G_POPUP, a popup menu (AES 4.1)",
    36: "G_WINTITLE, a window title (MagiC)",
    37: "G_EDIT, an editable field (MagiC)",
    38: "G_SHORTCUT, a keyboard shortcut marker (MagiC)",
    39: "G_SLIST, a scrolling list (XaAES)",
    40: "G_EXTBOX, an extended box (XaAES)",
    41: "G_OBLINK, a linked object (XaAES)",
  });

  const VDI_WRITING_MODES = Object.freeze({
    1: "MD_REPLACE, replace the destination",
    2: "MD_TRANS, transparent: only set pixels are drawn",
    3: "MD_XOR, exclusive-or with the destination",
    4: "MD_ERASE, reverse transparent: only clear pixels are drawn",
  });

  // The VDI's logical colour indexes and the colour each names in the
  // default palette. The hardware registers hold them in a different order.
  const DEFAULT_PALETTE = Object.freeze({
    0: "white", 1: "black", 2: "red", 3: "green", 4: "blue", 5: "cyan", 6: "yellow", 7: "magenta",
    8: "light grey", 9: "dark grey", 10: "light red", 11: "light green", 12: "light blue", 13: "light cyan",
    14: "light yellow", 15: "light magenta",
  });

  // The sixteen hardware palette registers at $FF8240 as TOS sets them in low
  // resolution, each with the $RGB value the ST writes there.
  const HARDWARE_PALETTE = Object.freeze({
    0: "white ($777)", 1: "red ($700)", 2: "green ($070)", 3: "yellow ($770)", 4: "blue ($007)", 5: "magenta ($707)",
    6: "cyan ($077)", 7: "light grey ($555)", 8: "dark grey ($333)", 9: "light red ($733)", 10: "light green ($373)",
    11: "light yellow ($773)", 12: "light blue ($337)", 13: "light magenta ($737)", 14: "light cyan ($377)", 15: "black ($000)",
  });

  // ------------------------------------------------------------ trap tables

  // A parameter is a word or a long on the stack after the function number;
  // the explain functions turn the list into 2(sp).w, 4(sp).l and so on.
  const w = (name, meaning, extra = {}) => ({ name, size: "w", meaning, ...extra });
  const l = (name, meaning, extra = {}) => ({ name, size: "l", meaning, ...extra });
  const call = (name, summary, parameters = [], extra = {}) => Object.freeze({ name, summary, parameters, ...extra });

  const STRING_POINTER = "pointer to a NUL-terminated string";
  const DTA_DESCRIPTION = "the 44-byte DTA that Fsfirst and Fsnext fill in";

  const GEMDOS = Object.freeze({
    0x00: call("Pterm0", "ends the program with an exit code of zero"),
    0x01: call("Cconin", "reads one character from the console, echoing it; the scan code is in the upper word"),
    0x02: call("Cconout", "writes one character to the console", [w("char", "character to write", { type: "character" })]),
    0x03: call("Cauxin", "reads one character from the serial port"),
    0x04: call("Cauxout", "writes one character to the serial port", [w("char", "character to write", { type: "character" })]),
    0x05: call("Cprnout", "writes one character to the printer", [w("char", "character to write", { type: "character" })]),
    0x06: call("Crawio", "raw console I/O: writes the character, or reads one without echo when it is $FF", [w("char", "character to write, or $FF to read", { type: "character" })]),
    0x07: call("Crawcin", "reads one character from the console without echo"),
    0x08: call("Cnecin", "reads one character from the console without echo, honouring control keys"),
    0x09: call("Cconws", "writes a NUL-terminated string to the console", [l("string", STRING_POINTER)]),
    0x0A: call("Cconrs", "reads an edited line from the console into a buffer", [l("buffer", "pointer to a buffer whose first byte holds the maximum length")]),
    0x0B: call("Cconis", "reports whether a console character is waiting; D0 is -1 when one is"),
    0x0E: call("Dsetdrv", "sets the default drive and returns the drive map in D0", [w("drive", "drive number, 0 for A:", { unit: "drive" })]),
    0x10: call("Cconos", "reports whether the console is ready to accept output"),
    0x11: call("Cprnos", "reports whether the printer is ready to accept output"),
    0x12: call("Cauxis", "reports whether a serial character is waiting"),
    0x13: call("Cauxos", "reports whether the serial port is ready to accept output"),
    0x19: call("Dgetdrv", "returns the default drive number, 0 for A:"),
    0x1A: call("Fsetdta", "sets the address of the disk transfer area", [l("dta", `pointer to ${DTA_DESCRIPTION}`)]),
    0x20: call("Super", "switches between user and supervisor mode, or queries the current mode", [l("stack", "0, 1 or a stack pointer", { values: SUPER_ARGUMENTS, otherwise: "a supervisor stack pointer to restore, returning the program to user mode" })]),
    0x2A: call("Tgetdate", "returns the system date in GEMDOS packed form"),
    0x2B: call("Tsetdate", "sets the system date", [w("date", "packed date: bits 15-9 year since 1980, 8-5 month, 4-0 day")]),
    0x2C: call("Tgettime", "returns the system time in GEMDOS packed form"),
    0x2D: call("Tsettime", "sets the system time", [w("time", "packed time: bits 15-11 hours, 10-5 minutes, 4-0 seconds divided by two")]),
    0x2F: call("Fgetdta", "returns the address of the current disk transfer area"),
    0x30: call("Sversion", "returns the GEMDOS version, minor byte first ($1300 is 0.19, $1500 is 0.21)"),
    0x31: call("Ptermres", "ends the program but keeps part of it resident in memory", [l("keep", "number of bytes to keep, counted from the basepage"), w("code", "exit code")]),
    0x36: call("Dfree", "fills a four-long structure with free clusters, total clusters, sector size and cluster size", [l("buffer", "pointer to a 16-byte buffer"), w("drive", "0 for the default drive, 1 for A:, 2 for B: and so on", { unit: "drive" })]),
    0x39: call("Dcreate", "creates a directory", [l("path", STRING_POINTER)]),
    0x3A: call("Ddelete", "deletes an empty directory", [l("path", STRING_POINTER)]),
    0x3B: call("Dsetpath", "sets the current directory of a drive", [l("path", STRING_POINTER)]),
    0x3C: call("Fcreate", "creates or truncates a file and returns a handle", [l("name", STRING_POINTER), w("attributes", "GEMDOS attribute byte", { bits: ATTRIBUTE_BITS })]),
    0x3D: call("Fopen", "opens an existing file and returns a handle in D0, or a negative error", [l("name", STRING_POINTER), w("mode", "access mode", { values: FOPEN_MODES, otherwise: "a MiNT sharing or inheritance mode" })]),
    0x3E: call("Fclose", "closes a file handle", [w("handle", "file handle from Fopen or Fcreate")]),
    0x3F: call("Fread", "reads bytes from a file handle into a buffer", [w("handle", "file handle"), l("count", "number of bytes to read", { unit: "byte" }), l("buffer", "destination buffer")]),
    0x40: call("Fwrite", "writes bytes from a buffer to a file handle", [w("handle", "file handle"), l("count", "number of bytes to write", { unit: "byte" }), l("buffer", "source buffer")]),
    0x41: call("Fdelete", "deletes a file", [l("name", STRING_POINTER)]),
    0x42: call("Fseek", "moves a file's read and write position and returns the new position", [l("offset", "signed offset", { unit: "byte" }), w("handle", "file handle"), w("mode", "where the offset is measured from", { values: FSEEK_MODES })]),
    0x43: call("Fattrib", "reads or sets a file's attribute byte", [l("name", STRING_POINTER), w("flag", "0 to read the attributes, 1 to set them"), w("attributes", "GEMDOS attribute byte", { bits: ATTRIBUTE_BITS })]),
    0x45: call("Fdup", "duplicates one of the standard handles 0 to 5 and returns a new handle", [w("handle", "standard handle to duplicate")]),
    0x46: call("Fforce", "redirects a standard handle onto another handle", [w("standard", "standard handle to redirect"), w("handle", "handle it is redirected to")]),
    0x47: call("Dgetpath", "copies a drive's current directory into a buffer", [l("buffer", "pointer to a 64-byte buffer"), w("drive", "0 for the default drive, 1 for A: and so on", { unit: "drive" })]),
    0x48: call("Malloc", "allocates memory, or reports the largest free block when the size is -1", [l("size", "number of bytes, or -1 to ask for the largest free block", { unit: "byte" })]),
    0x49: call("Mfree", "frees a block allocated with Malloc", [l("block", "address returned by Malloc")]),
    0x4A: call("Mshrink", "shrinks a block, normally the program's own TPA, to a new size", [w("zero", "always 0"), l("block", "start of the block"), l("size", "new size", { unit: "byte" })]),
    0x4B: call("Pexec", "loads, runs or prepares another program", [w("mode", "how the program is loaded and run", { values: PEXEC_MODES, otherwise: "a MiNT extended mode, such as 100 for an asynchronous load and go" }), l("name", "program path, or a basepage for the go modes"), l("command", "command tail: a length byte and up to 125 characters"), l("environment", "environment string, or 0 for the parent's")]),
    0x4C: call("Pterm", "ends the program with an exit code", [w("code", "exit code returned to the parent")]),
    0x4E: call("Fsfirst", "searches for the first directory entry matching a pattern and fills the DTA", [l("pattern", "pointer to a path with wildcards"), w("attributes", "attribute bits that may also match", { bits: ATTRIBUTE_BITS })]),
    0x4F: call("Fsnext", "finds the next entry after Fsfirst, using the same DTA"),
    0x56: call("Frename", "renames or moves a file within a drive", [w("zero", "always 0"), l("old", "current name"), l("new", "new name")]),
    0x57: call("Fdatime", "reads or sets a file's date and time stamp", [l("stamp", "pointer to a time word followed by a date word"), w("handle", "file handle"), w("flag", "0 to read the stamp, 1 to set it")]),
  });

  const BIOS = Object.freeze({
    0: call("Getmpb", "fills in the memory parameter block; only the operating system should call it", [l("mpb", "pointer to a 12-byte MPB")]),
    1: call("Bconstat", "reports whether a character is waiting on a device; D0 is -1 when one is", [w("device", "device number", { values: BCONOUT_DEVICES })]),
    2: call("Bconin", "reads one character from a device, waiting for it", [w("device", "device number", { values: BCONOUT_DEVICES })]),
    3: call("Bconout", "writes one character to a device", [w("device", "device number", { values: BCONOUT_DEVICES }), w("char", "character to write", { type: "character" })]),
    4: call("Rwabs", "reads or writes whole sectors on a drive", [w("mode", "direction and media-change handling", { bits: RWABS_FLAGS }), l("buffer", "sector buffer, ideally word aligned"), w("count", "number of sectors", { unit: "sector" }), w("sector", "first logical sector"), w("drive", "drive number, 0 for A:", { unit: "drive" })]),
    5: call("Setexc", "reads or replaces an exception vector and returns the old one", [w("vector", "vector number: the address divided by four"), l("handler", "new handler, or -1 to only read")]),
    6: call("Tickcal", "returns the system timer period in milliseconds"),
    7: call("Getbpb", "returns a drive's BIOS parameter block, or 0 when the medium is unknown", [w("drive", "drive number, 0 for A:", { unit: "drive" })]),
    8: call("Bcostat", "reports whether a device can accept a character", [w("device", "device number", { values: BCONOUT_DEVICES })]),
    9: call("Mediach", "reports whether the medium in a drive has changed", [w("drive", "drive number, 0 for A:", { unit: "drive" })], { result: MEDIACH_RESULTS }),
    10: call("Drvmap", "returns a bit map of the drives present, bit 0 for A:"),
    11: call("Kbshift", "reads or sets the keyboard shift state", [w("mode", "-1 to read, or the new shift bits: 1 right shift, 2 left shift, 4 control, 8 alternate, 16 caps lock, 32 right mouse button, 64 left mouse button")]),
  });

  const XBIOS = Object.freeze({
    0: call("Initmous", "installs a mouse handler and sets the mouse mode", [w("type", "0 disable, 1 relative, 2 absolute, 3 unused, 4 keycode"), l("parameters", "pointer to the mouse parameter block"), l("handler", "mouse packet handler")]),
    1: call("Ssbrk", "reserves memory at the top of RAM before the system starts; useless after boot", [w("size", "bytes to reserve", { unit: "byte" })]),
    2: call("Physbase", "returns the physical screen base address"),
    3: call("Logbase", "returns the logical screen base address the VDI draws into"),
    4: call("Getrez", "returns the current screen resolution", [], { result: GETREZ_VALUES }),
    5: call("Setscreen", "sets the logical and physical screen bases and the resolution", [l("logical", "new logical base, or -1 to leave it"), l("physical", "new physical base, or -1 to leave it"), w("resolution", "new resolution, or -1 to leave it", { values: GETREZ_VALUES, otherwise: "-1 to keep the current resolution, or a Falcon mode code when the call is Setscreen(-1,-1,3,mode)" })]),
    6: call("Setpalette", "loads all sixteen palette registers at the next vertical blank", [l("palette", "pointer to sixteen words of $RGB")]),
    7: call("Setcolor", "sets one palette register and returns the old value", [w("index", "palette register", { values: HARDWARE_PALETTE }), w("colour", "$RGB value, or -1 to only read")]),
    8: call("Floprd", "reads sectors from a floppy disk directly", [l("buffer", "buffer"), l("filler", "unused"), w("drive", "0 for A:, 1 for B:", { unit: "drive" }), w("sector", "first sector, from 1"), w("track", "track"), w("side", "side"), w("count", "sectors to read", { unit: "sector" })]),
    9: call("Flopwr", "writes sectors to a floppy disk directly", [l("buffer", "buffer"), l("filler", "unused"), w("drive", "0 for A:, 1 for B:", { unit: "drive" }), w("sector", "first sector, from 1"), w("track", "track"), w("side", "side"), w("count", "sectors to write", { unit: "sector" })]),
    10: call("Flopfmt", "formats one track of a floppy disk", [l("buffer", "scratch buffer of at least 8 KiB"), l("skew", "pointer to a sector skew table, or 0"), w("drive", "0 for A:, 1 for B:", { unit: "drive" }), w("sectors", "sectors per track, 9 or 10"), w("track", "track"), w("side", "side"), w("interleave", "1 for sequential sectors, or -1 to use the skew table"), l("magic", "must be $87654321"), w("virgin", "initial data word, normally $E5E5")]),
    11: call("Dbmsg", "sends a message to a debugger, if one is resident", [w("reserved", "must be 5"), w("number", "message number"), l("argument", "message argument")]),
    12: call("Midiws", "writes a string to the MIDI port", [w("count", "length minus one"), l("string", "pointer to the bytes")]),
    13: call("Mfpint", "installs an MFP 68901 interrupt handler", [w("number", "MFP interrupt number, 0 to 15"), l("handler", "interrupt handler")]),
    14: call("Iorec", "returns the address of a device's input or output buffer record", [w("device", "0 RS-232, 1 keyboard, 2 MIDI")]),
    15: call("Rsconf", "configures the RS-232 port and returns the old settings", [w("speed", "baud rate code, 0 for 19200 down to 15 for 50, or -1 to leave it"), w("flow", "0 none, 1 XON/XOFF, 2 RTS/CTS, 3 both"), w("ucr", "MFP UCR, or -1"), w("rsr", "MFP RSR, or -1"), w("tsr", "MFP TSR, or -1"), w("scr", "MFP SCR, or -1")]),
    16: call("Keytbl", "installs keyboard translation tables and returns their address", [l("unshifted", "table, or -1"), l("shifted", "table, or -1"), l("capslock", "table, or -1")]),
    17: call("Random", "returns a 24-bit pseudo-random number"),
    18: call("Protobt", "builds a boot sector in a buffer", [l("buffer", "512-byte buffer"), l("serial", "serial number, or -1 to keep, or $01000000 for a random one"), w("type", "disk type: 0 40 tracks single sided, 1 40 tracks double sided, 2 80 tracks single sided, 3 80 tracks double sided, or -1 to keep"), w("executable", "0 not bootable, 1 bootable, or -1 to keep")]),
    19: call("Flopver", "verifies floppy sectors against a buffer", [l("buffer", "buffer"), l("filler", "unused"), w("drive", "0 for A:, 1 for B:", { unit: "drive" }), w("sector", "first sector"), w("track", "track"), w("side", "side"), w("count", "sectors to verify", { unit: "sector" })]),
    20: call("Scrdmp", "dumps the screen to the printer"),
    21: call("Cursconf", "configures the text cursor", [w("function", "0 hide, 1 show, 2 blink, 3 steady, 4 set rate, 5 read rate"), w("rate", "blink rate in vertical blanks")]),
    22: call("Settime", "sets the keyboard controller's clock", [l("datetime", "packed date in the high word and packed time in the low word")]),
    23: call("Gettime", "reads the keyboard controller's clock as a packed date and time"),
    24: call("Bioskeys", "restores the default keyboard tables"),
    25: call("Ikbdws", "writes a command string to the keyboard controller", [w("count", "length minus one"), l("string", "pointer to the bytes")]),
    26: call("Jdisint", "disables an MFP interrupt", [w("number", "MFP interrupt number, 0 to 15")]),
    27: call("Jenabint", "enables an MFP interrupt", [w("number", "MFP interrupt number, 0 to 15")]),
    28: call("Giaccess", "reads or writes a sound chip register", [w("data", "value to write"), w("register", "register number; add $80 to write")]),
    29: call("Offgibit", "clears bits in the sound chip's port A, which drives floppy selects and RS-232 lines", [w("mask", "bits to clear")]),
    30: call("Ongibit", "sets bits in the sound chip's port A", [w("mask", "bits to set")]),
    31: call("Xbtimer", "programs one of the MFP timers", [w("timer", "0 A, 1 B, 2 C, 3 D"), w("control", "timer control value"), w("data", "timer data value"), l("handler", "interrupt handler")]),
    32: call("Dosound", "starts playing a sound chip command list at each vertical blank", [l("commands", "pointer to the command bytes, or -1 to read the current pointer")]),
    33: call("Setprt", "reads or sets the printer configuration", [w("config", "configuration bits, or -1 to read")]),
    34: call("Kbdvbase", "returns the keyboard and MIDI vector table"),
    35: call("Kbrate", "reads or sets the key repeat delay and rate", [w("initial", "delay before repeating, in 50 Hz ticks, or -1"), w("repeat", "ticks between repeats, or -1")]),
    36: call("Prtblk", "prints a block of the screen", [l("parameters", "pointer to the print parameter block")]),
    37: call("Vsync", "waits for the next vertical blank"),
    38: call("Supexec", "runs a routine in supervisor mode", [l("routine", "routine ending in RTS")]),
    39: call("Puntaes", "discards the AES and reboots without it; only works when GEM is in RAM (TOS 1.00 to 1.04)"),
    41: call("Floprate", "sets a floppy drive's seek rate", [w("drive", "0 for A:, 1 for B:", { unit: "drive" }), w("rate", "0 6 ms, 1 12 ms, 2 2 ms, 3 3 ms, or -1 to read")], { platforms: DEFAULT_MACHINES, requires: "TOS 1.04 or later" }),
    42: call("DMAread", "reads sectors from an ACSI or SCSI device through the DMA controller", [l("sector", "first sector"), w("count", "sectors", { unit: "sector" }), l("buffer", "buffer"), w("device", "device number, 0 to 7 for ACSI, 8 to 15 for SCSI")], { requires: "TOS 2.00 or later" }),
    43: call("DMAwrite", "writes sectors to an ACSI or SCSI device through the DMA controller", [l("sector", "first sector"), w("count", "sectors", { unit: "sector" }), l("buffer", "buffer"), w("device", "device number, 0 to 7 for ACSI, 8 to 15 for SCSI")], { requires: "TOS 2.00 or later" }),
    44: call("Bconmap", "maps a BIOS device number onto a physical serial port, or reports the mapping", [w("device", "device number 6 or above to map, -1 to read the current mapping, -2 to get the table", { values: BCONOUT_DEVICES })], { platforms: EXTRA_SERIAL_MACHINES, requires: "TOS 1.02 or later on a machine with more than one serial port" }),
    46: call("NVMaccess", "reads, writes or resets the battery-backed NVRAM", [w("operation", "0 read, 1 write, 2 reset"), w("start", "first byte"), w("count", "number of bytes", { unit: "byte" }), l("buffer", "buffer")], { platforms: TT_AND_FALCON, requires: "a TT or Falcon with NVRAM" }),
    64: call("Blitmode", "reads or sets whether the VDI uses the blitter", [w("mode", "-1 to read; bit 0 set to use the blitter; bit 1 in the result says one is fitted")], { platforms: BLITTER_MACHINES, requires: "a machine with a blitter and TOS 1.02 or later" }),
    80: call("EsetShift", "sets the STE shifter mode register", [w("mode", "shift mode word")], { platforms: STE_AND_LATER, requires: "an STE shifter" }),
    81: call("EgetShift", "reads the STE shifter mode register", [], { platforms: STE_AND_LATER, requires: "an STE shifter" }),
    82: call("EsetBank", "selects one of the STE's palette banks", [w("bank", "bank number, or -1 to read")], { platforms: STE_AND_LATER, requires: "an STE shifter" }),
    83: call("EsetColor", "sets one STE palette register with 4-bit components", [w("index", "palette register"), w("colour", "$RGB with 4 bits per component, or -1 to read")], { platforms: STE_AND_LATER, requires: "an STE shifter" }),
    84: call("EsetPalette", "sets several STE palette registers", [w("start", "first register"), w("count", "number of registers"), l("palette", "pointer to the colour words")], { platforms: STE_AND_LATER, requires: "an STE shifter" }),
    85: call("EgetPalette", "reads several STE palette registers", [w("start", "first register"), w("count", "number of registers"), l("palette", "buffer for the colour words")], { platforms: STE_AND_LATER, requires: "an STE shifter" }),
    86: call("EsetGray", "switches the TT palette between colour and grey scale", [w("mode", "0 colour, 1 grey, or -1 to read")], { platforms: TT_ONLY, requires: "a TT" }),
    87: call("EsetSmear", "sets the TT smear mode", [w("mode", "0 normal, 1 smear, or -1 to read")], { platforms: TT_ONLY, requires: "a TT" }),
    88: call("VsetMode", "sets the Falcon video mode and returns the old one", [w("mode", "Falcon mode word: bits 0-2 bits per pixel, 3 80 columns, 4 VGA, 5 PAL, 6 overscan, 7 ST compatible, 8 interlace; -1 to read")], { platforms: FALCON_ONLY, requires: "a Falcon VIDEL" }),
    89: call("mon_type", "reports the monitor connected to a Falcon: 0 ST monochrome, 1 ST colour, 2 VGA, 3 television", [], { platforms: FALCON_ONLY, requires: "a Falcon" }),
    90: call("VsetSync", "selects internal or external video synchronisation on a Falcon", [w("flags", "bit 0 external clock, bit 1 external vertical sync, bit 2 external horizontal sync")], { platforms: FALCON_ONLY, requires: "a Falcon VIDEL" }),
    91: call("VgetSize", "returns the number of bytes a Falcon video mode needs", [w("mode", "Falcon mode word")], { platforms: FALCON_ONLY, requires: "a Falcon VIDEL" }),
    93: call("VsetRGB", "sets Falcon palette entries with 8-bit components", [w("index", "first entry"), w("count", "number of entries"), l("array", "pointer to longs of $00RRGGBB")], { platforms: FALCON_ONLY, requires: "a Falcon VIDEL" }),
    94: call("VgetRGB", "reads Falcon palette entries", [w("index", "first entry"), w("count", "number of entries"), l("array", "buffer for longs of $00RRGGBB")], { platforms: FALCON_ONLY, requires: "a Falcon VIDEL" }),
    96: call("Dsp_DoBlock", "sends a block of data to the DSP and reads a block back", [l("data_in", "data to send"), l("size_in", "longs to send"), l("data_out", "buffer for the result"), l("size_out", "longs to receive")], { platforms: FALCON_ONLY, requires: "the Falcon's DSP 56001" }),
    128: call("Locksnd", "locks the sound system for this program", [], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    129: call("Unlocksnd", "unlocks the sound system", [], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    130: call("Soundcmd", "sets a sound system parameter such as gain, attenuation or ADC input", [w("mode", "0 left gain, 1 right gain, 2 left attenuation, 3 right attenuation, 4 ADC input, 5 ADDERIN, 6 ADC adjust, 7 prescale"), w("data", "value, or -1 to read")], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    131: call("Setbuffer", "sets the record or playback buffer", [w("mode", "0 playback, 1 record"), l("start", "buffer start"), l("end", "buffer end")], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    132: call("Setmode", "sets the sample format", [w("mode", "0 8-bit stereo, 1 16-bit stereo, 2 8-bit mono")], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    133: call("Settracks", "sets the number of playback and record tracks", [w("playback", "tracks, 0 to 3"), w("record", "tracks, 0 to 3")], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    134: call("Setmontracks", "selects the track sent to the internal speaker", [w("track", "track, 0 to 3")], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    135: call("Setinterrupt", "chooses the interrupt raised at the end of a buffer", [w("source", "0 Timer A, 1 MFP interrupt 7"), w("cause", "0 none, 1 end of playback, 2 end of record, 3 both")], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    136: call("Buffoper", "starts or stops playback and recording", [w("mode", "bit 0 play, bit 1 repeat play, bit 2 record, bit 3 repeat record")], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    137: call("Dsptristate", "connects or disconnects the DSP from the sound matrix", [w("dspxmit", "0 disconnect, 1 connect"), w("dsprec", "0 disconnect, 1 connect")], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    138: call("Gpio", "reads or writes the general purpose pins on the DSP connector", [w("mode", "0 set direction, 1 read, 2 write"), w("data", "value")], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    139: call("Devconnect", "connects a source to destinations in the sound matrix and sets the clock", [w("source", "0 DMA playback, 1 DSP transmit, 2 external input, 3 ADC"), w("destination", "bit 0 DMA record, 1 DSP receive, 2 external output, 3 DAC"), w("clock", "0 internal 25.175 MHz, 1 external, 2 internal 32 MHz"), w("prescale", "frequency divider: 1 for 49170 Hz, 2 for 32780, 3 for 24585, 4 for 19668, 5 for 16390, 7 for 12292, 9 for 9834, 11 for 8195"), w("protocol", "0 handshake, 1 none")], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    140: call("Sndstatus", "reports the sound system state and optionally resets it", [w("reset", "1 to reset")], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
    141: call("Buffptr", "reads the current record and playback positions", [l("pointer", "buffer for four longs")], { platforms: FALCON_ONLY, requires: "the Falcon sound system" }),
  });

  // AES functions, keyed by control[0]. Each entry lists the int_in and
  // addr_in slots the function reads.
  const i = (name, meaning, extra = {}) => ({ name, array: "int_in", meaning, ...extra });
  const a = (name, meaning, extra = {}) => ({ name, array: "addr_in", meaning, ...extra });
  const RECT = (prefix = "") => [i(`${prefix}x`, "x"), i(`${prefix}y`, "y"), i(`${prefix}w`, "width"), i(`${prefix}h`, "height")];

  const AES = Object.freeze({
    10: call("appl_init", "registers the program with the AES and returns its application id in D0"),
    11: call("appl_read", "reads bytes from another application's message pipe", [i("ap_id", "application id"), i("length", "bytes to read", { unit: "byte" }), a("buffer", "destination buffer")]),
    12: call("appl_write", "writes a message to another application's pipe", [i("ap_id", "application id"), i("length", "bytes to write, normally 16", { unit: "byte" }), a("buffer", "message buffer")]),
    13: call("appl_find", "finds an application by its 8-character name and returns its id", [a("name", "name padded with spaces")]),
    14: call("appl_tplay", "plays back recorded AES events", [a("buffer", "event buffer"), i("count", "number of events"), i("scale", "playback speed, 100 for real time")]),
    15: call("appl_trecord", "records AES events into a buffer", [a("buffer", "event buffer"), i("count", "maximum events")]),
    19: call("appl_exit", "tells the AES the program is finishing"),
    20: call("evnt_keybd", "waits for a key press and returns its scan and ASCII codes"),
    21: call("evnt_button", "waits for a mouse button state", [i("clicks", "number of clicks to wait for"), i("mask", "buttons to watch, bit 0 left"), i("state", "button state to wait for")]),
    22: call("evnt_mouse", "waits for the mouse to enter or leave a rectangle", [i("flag", "0 entering, 1 leaving"), ...RECT()]),
    23: call("evnt_mesag", "waits for a message", [a("buffer", "16-byte message buffer")]),
    24: call("evnt_timer", "waits for a period to elapse", [i("low", "low word of the milliseconds", { unit: "millisecond" }), i("high", "high word of the milliseconds")]),
    25: call("evnt_multi", "waits for any of several kinds of event", [i("flags", "events to wait for", { bits: EVNT_MULTI_FLAGS }), i("clicks", "button clicks"), i("mask", "button mask"), i("state", "button state"), i("m1flag", "rectangle 1 entering or leaving"), ...RECT("m1"), i("m2flag", "rectangle 2 entering or leaving"), ...RECT("m2"), a("buffer", "message buffer"), i("low", "timer low word"), i("high", "timer high word")]),
    26: call("evnt_dclick", "reads or sets the double-click speed", [i("rate", "0 slowest to 4 fastest"), i("flag", "0 read, 1 set")]),
    30: call("menu_bar", "shows or hides a menu bar", [a("tree", "menu object tree"), i("mode", "0 hide, 1 show, -1 query the owner (AES 4)")]),
    31: call("menu_icheck", "sets or clears a menu item's check mark", [a("tree", "menu object tree"), i("item", "object index"), i("check", "0 clear, 1 check")]),
    32: call("menu_ienable", "enables or disables a menu item", [a("tree", "menu object tree"), i("item", "object index"), i("enable", "0 disable, 1 enable")]),
    33: call("menu_tnormal", "shows a menu title normally or highlighted", [a("tree", "menu object tree"), i("title", "title object index"), i("normal", "1 normal, 0 highlighted")]),
    34: call("menu_text", "replaces a menu item's text", [a("tree", "menu object tree"), i("item", "object index"), a("text", "new text, no longer than the old")]),
    35: call("menu_register", "registers a desk accessory in the Desk menu and returns its menu id", [i("ap_id", "application id"), a("text", "menu text")]),
    40: call("objc_add", "adds an object to a tree as the last child of a parent", [a("tree", "object tree"), i("parent", "parent index"), i("child", "child index")]),
    41: call("objc_delete", "removes an object from its tree", [a("tree", "object tree"), i("object", "object index")]),
    42: call("objc_draw", "draws an object and its children within a clip rectangle", [a("tree", "object tree"), i("start", "first object"), i("depth", "levels to descend"), ...RECT("clip")]),
    43: call("objc_find", "finds the object under a screen position", [a("tree", "object tree"), i("start", "first object"), i("depth", "levels to descend"), i("x", "screen x"), i("y", "screen y")]),
    44: call("objc_offset", "returns an object's absolute screen position", [a("tree", "object tree"), i("object", "object index")]),
    45: call("objc_order", "moves an object within its siblings", [a("tree", "object tree"), i("object", "object index"), i("position", "new position, -1 for last")]),
    46: call("objc_edit", "edits the text of an editable object", [a("tree", "object tree"), i("object", "object index"), i("char", "character typed", { type: "character" }), i("index", "cursor index"), i("kind", "0 reserved, 1 init, 2 character, 3 end")]),
    47: call("objc_change", "changes an object's state and redraws it", [a("tree", "object tree"), i("object", "object index"), i("reserved", "0"), ...RECT("clip"), i("state", "new object state"), i("redraw", "0 no, 1 yes")]),
    50: call("form_do", "runs a dialog until an exit object is selected", [a("tree", "object tree"), i("start", "editable object to start in, or 0")]),
    51: call("form_dial", "reserves, releases or animates a dialog's screen area", [i("flag", "0 reserve, 1 grow, 2 shrink, 3 release"), ...RECT("small"), ...RECT("big")]),
    52: call("form_alert", "shows an alert box and returns the button chosen", [i("default", "default button, 1 to 3"), a("text", "alert string [icon][text][buttons]")], { result: FORM_ALERT_ICONS }),
    53: call("form_error", "shows an alert for a GEMDOS error", [i("error", "error number minus 31")]),
    54: call("form_center", "centres a dialog on the screen and returns its rectangle", [a("tree", "object tree")]),
    55: call("form_keybd", "processes a key press for a dialog", [a("tree", "object tree"), i("object", "current object"), i("next", "next object"), i("char", "key", { type: "character" })]),
    56: call("form_button", "processes a mouse click for a dialog", [a("tree", "object tree"), i("object", "object clicked"), i("clicks", "number of clicks")]),
    70: call("graf_rubberbox", "lets the user drag out a rubber-band rectangle", [i("x", "anchor x"), i("y", "anchor y"), i("minw", "minimum width"), i("minh", "minimum height")]),
    71: call("graf_dragbox", "lets the user drag a box within a boundary", [i("w", "width"), i("h", "height"), i("x", "start x"), i("y", "start y"), ...RECT("bound")]),
    72: call("graf_movebox", "animates a box moving from one place to another", [i("w", "width"), i("h", "height"), i("fromx", "from x"), i("fromy", "from y"), i("tox", "to x"), i("toy", "to y")]),
    73: call("graf_growbox", "animates a box growing", [...RECT("small"), ...RECT("big")]),
    74: call("graf_shrinkbox", "animates a box shrinking", [...RECT("small"), ...RECT("big")]),
    75: call("graf_watchbox", "tracks the mouse over an object while a button is held", [a("tree", "object tree"), i("object", "object index"), i("in", "state while inside"), i("out", "state while outside")]),
    76: call("graf_slidebox", "lets the user drag a slider inside its parent", [a("tree", "object tree"), i("parent", "parent index"), i("object", "slider index"), i("vertical", "0 horizontal, 1 vertical")]),
    77: call("graf_handle", "returns the AES's VDI handle and the character cell size"),
    78: call("graf_mouse", "changes the mouse shape", [i("form", "0 arrow, 1 text cursor, 2 bee, 3 pointing hand, 4 flat hand, 5 thin cross, 6 thick cross, 7 outline cross, 255 user defined, 256 hide, 257 show"), a("form", "user-defined mouse form when form is 255")]),
    79: call("graf_mkstate", "returns the mouse position, button state and shift keys"),
    80: call("scrp_read", "reads the scrap directory path", [a("buffer", "buffer for the path")]),
    81: call("scrp_write", "sets the scrap directory path", [a("path", "new path")]),
    90: call("fsel_input", "shows the file selector", [a("path", "path buffer with a mask"), a("name", "file name buffer")]),
    91: call("fsel_exinput", "shows the file selector with a title", [a("path", "path buffer with a mask"), a("name", "file name buffer"), a("title", "title string")], { requires: "TOS 1.04 or later" }),
    100: call("wind_create", "creates a window and returns its handle", [i("kind", "window element bits: 1 NAME, 2 CLOSER, 4 FULLER, 8 MOVER, 16 INFO, 32 SIZER, 64 UPARROW, 128 DNARROW, 256 VSLIDE, 512 LFARROW, 1024 RTARROW, 2048 HSLIDE"), ...RECT("max")]),
    101: call("wind_open", "opens a created window at a size", [i("handle", "window handle"), ...RECT()]),
    102: call("wind_close", "closes a window without deleting it", [i("handle", "window handle")]),
    103: call("wind_delete", "deletes a closed window", [i("handle", "window handle")]),
    104: call("wind_get", "reads a window attribute", [i("handle", "window handle"), i("field", "WF_ field: 4 WORKXYWH, 5 CURRXYWH, 6 PREVXYWH, 7 FULLXYWH, 8 HSLIDE, 9 VSLIDE, 10 TOP, 11 FIRSTXYWH, 12 NEXTXYWH, 15 HSLSIZE, 16 VSLSIZE, 17 SCREEN")]),
    105: call("wind_set", "sets a window attribute", [i("handle", "window handle"), i("field", "WF_ field: 2 NAME, 3 INFO, 5 CURRXYWH, 8 HSLIDE, 9 VSLIDE, 10 TOP, 14 NEWDESK, 15 HSLSIZE, 16 VSLSIZE"), i("value1", "first value"), i("value2", "second value"), i("value3", "third value"), i("value4", "fourth value")]),
    106: call("wind_find", "finds the window under a screen position", [i("x", "screen x"), i("y", "screen y")]),
    107: call("wind_update", "begins or ends a screen update or mouse control", [i("mode", "0 END_UPDATE, 1 BEG_UPDATE, 2 END_MCTRL, 3 BEG_MCTRL")]),
    108: call("wind_calc", "converts between a window's border and work rectangles", [i("type", "0 border from work, 1 work from border"), i("kind", "window element bits"), ...RECT()]),
    109: call("wind_new", "closes and deletes every window (TOS 1.04 or later)", [], { requires: "TOS 1.04 or later" }),
    110: call("rsrc_load", "loads a resource file", [a("name", "file name")]),
    111: call("rsrc_free", "frees the loaded resource"),
    112: call("rsrc_gaddr", "returns the address of a resource object", [i("type", "0 tree, 1 object, 2 TEDINFO, 3 ICONBLK, 4 BITBLK, 5 string, 6 image, 7 object pointer, 8 TEDINFO pointer, 9 ICONBLK pointer, 10 BITBLK pointer, 11 free string, 12 free image"), i("index", "index within that type")]),
    113: call("rsrc_saddr", "stores the address of a resource object", [i("type", "resource type"), i("index", "index"), a("address", "new address")]),
    114: call("rsrc_obfix", "converts an object's character coordinates to pixels", [a("tree", "object tree"), i("object", "object index")]),
    120: call("shel_read", "reads the command and tail this program was started with", [a("command", "command buffer"), a("tail", "tail buffer")]),
    121: call("shel_write", "asks the shell to run a program, or extends the AES (AES 4)", [i("doex", "0 return to the desktop, 1 run a program, or an extended mode"), i("isgr", "0 TOS program, 1 GEM program"), i("iscr", "0 program, 1 desk accessory"), a("command", "program name"), a("tail", "command tail")]),
    122: call("shel_get", "reads the shell's buffer, normally DESKTOP.INF or NEWDESK.INF", [a("buffer", "destination"), i("length", "bytes to copy", { unit: "byte" })]),
    123: call("shel_put", "writes the shell's buffer", [a("buffer", "source"), i("length", "bytes to copy", { unit: "byte" })]),
    124: call("shel_find", "finds a file on the AES search path", [a("buffer", "file name in, full path out")]),
    125: call("shel_envrn", "finds an environment variable", [a("value", "pointer to receive the value address"), a("name", "variable name ending in =")]),
  });

  // VDI functions keyed by contrl[0]; escapes (5) and GDPs (11) by contrl[5].
  const c = (name, meaning, extra = {}) => ({ name, array: "contrl", meaning, ...extra });
  const pt = (name, meaning, extra = {}) => ({ name, array: "ptsin", meaning, ...extra });
  const vi = (name, meaning, extra = {}) => ({ name, array: "intin", meaning, ...extra });

  const VDI = Object.freeze({
    1: call("v_opnwk", "opens a physical workstation and returns its handle", [vi("work_in", "eleven words: device id, line type, line colour, marker type, marker colour, font, text colour, fill interior, fill style, fill colour, coordinate flag")]),
    2: call("v_clswk", "closes a physical workstation"),
    3: call("v_clrwk", "clears the workstation"),
    4: call("v_updwk", "flushes pending output to the workstation"),
    5: Object.freeze({
      name: "escape", summary: "an escape function selected by contrl[5]",
      subfunctions: Object.freeze({
        1: call("vq_chcells", "returns the number of text rows and columns"),
        2: call("v_exit_cur", "leaves alpha cursor mode and restores graphics"),
        3: call("v_enter_cur", "enters alpha cursor mode and clears the screen"),
        4: call("v_curup", "moves the text cursor up one row"),
        5: call("v_curdown", "moves the text cursor down one row"),
        6: call("v_curright", "moves the text cursor right one column"),
        7: call("v_curleft", "moves the text cursor left one column"),
        8: call("v_curhome", "moves the text cursor to the top left"),
        9: call("v_eeos", "erases to the end of the screen"),
        10: call("v_eeol", "erases to the end of the line"),
        11: call("vs_curaddress", "moves the text cursor", [vi("row", "row, from 1"), vi("column", "column, from 1")]),
        12: call("v_curtext", "writes text at the cursor in alpha mode", [vi("string", "characters as words")]),
        13: call("v_rvon", "turns reverse video on"),
        14: call("v_rvoff", "turns reverse video off"),
        15: call("vq_curaddress", "returns the text cursor position"),
        16: call("vq_tabstatus", "reports whether a tablet is available"),
        17: call("v_hardcopy", "prints the screen"),
        18: call("v_dspcur", "shows the mouse cursor at a position", [pt("x", "x"), pt("y", "y")]),
        19: call("v_rmcur", "removes the mouse cursor"),
        20: call("v_form_adv", "advances the printer a page"),
        21: call("v_output_window", "prints part of the screen"),
        22: call("v_clear_disp_list", "clears the printer's display list"),
        23: call("v_bit_image", "prints a bit image file"),
        98: call("v_meta_extents", "sets a metafile's extents"),
        99: call("v_write_meta", "writes a user record into a metafile"),
        100: call("vm_filename", "names the metafile"),
      }),
    }),
    6: call("v_pline", "draws a polyline through contrl[1] points", [c("1", "number of points"), pt("xy", "point coordinates")]),
    7: call("v_pmarker", "draws markers at contrl[1] points", [c("1", "number of points"), pt("xy", "point coordinates")]),
    8: call("v_gtext", "draws graphic text at a point", [pt("x", "x"), pt("y", "y"), vi("string", "characters as words"), c("3", "number of characters")]),
    9: call("v_fillarea", "fills a polygon of contrl[1] points", [c("1", "number of points"), pt("xy", "point coordinates")]),
    10: call("v_cellarray", "draws a cell array of colours", [pt("xy", "rectangle corners"), vi("colours", "colour indexes")]),
    11: Object.freeze({
      name: "GDP", summary: "a generalised drawing primitive selected by contrl[5]",
      subfunctions: Object.freeze({
        1: call("v_bar", "draws a filled rectangle", [pt("xy", "two corners")]),
        2: call("v_arc", "draws an arc", [pt("x", "centre x"), pt("y", "centre y"), pt("radius", "radius in ptsin[6]"), vi("begin", "start angle in tenths of a degree"), vi("end", "end angle in tenths of a degree")]),
        3: call("v_pieslice", "draws a filled pie slice", [pt("x", "centre x"), pt("y", "centre y"), pt("radius", "radius in ptsin[6]"), vi("begin", "start angle"), vi("end", "end angle")]),
        4: call("v_circle", "draws a filled circle", [pt("x", "centre x"), pt("y", "centre y"), pt("radius", "radius in ptsin[4]")]),
        5: call("v_ellipse", "draws a filled ellipse", [pt("x", "centre x"), pt("y", "centre y"), pt("xradius", "x radius"), pt("yradius", "y radius")]),
        6: call("v_ellarc", "draws an elliptical arc", [pt("x", "centre x"), pt("y", "centre y"), pt("xradius", "x radius"), pt("yradius", "y radius"), vi("begin", "start angle"), vi("end", "end angle")]),
        7: call("v_ellpie", "draws a filled elliptical pie slice", [pt("x", "centre x"), pt("y", "centre y"), pt("xradius", "x radius"), pt("yradius", "y radius"), vi("begin", "start angle"), vi("end", "end angle")]),
        8: call("v_rbox", "draws a rounded rectangle outline", [pt("xy", "two corners")]),
        9: call("v_rfbox", "draws a filled rounded rectangle", [pt("xy", "two corners")]),
        10: call("v_justified", "draws text justified to a width", [pt("x", "x"), pt("y", "y"), pt("width", "width"), vi("word", "word spacing flag"), vi("char", "character spacing flag"), vi("string", "characters as words")]),
      }),
    }),
    12: call("vst_height", "sets the text height in pixels", [pt("height", "height in ptsin[1]")]),
    13: call("vst_rotation", "sets the text baseline angle", [vi("angle", "tenths of a degree")]),
    14: call("vs_color", "sets a colour index's red, green and blue", [vi("index", "colour index", { values: DEFAULT_PALETTE }), vi("red", "0 to 1000"), vi("green", "0 to 1000"), vi("blue", "0 to 1000")]),
    15: call("vsl_type", "sets the line type", [vi("type", "1 solid, 2 long dash, 3 dot, 4 dash dot, 5 dash, 6 dash dot dot, 7 user defined")]),
    16: call("vsl_width", "sets the line width", [pt("width", "width in pixels, odd numbers only")]),
    17: call("vsl_color", "sets the line colour", [vi("index", "colour index", { values: DEFAULT_PALETTE })]),
    18: call("vsm_type", "sets the marker type", [vi("type", "1 dot, 2 plus, 3 asterisk, 4 square, 5 diagonal cross, 6 diamond")]),
    19: call("vsm_height", "sets the marker height", [pt("height", "height in ptsin[1]")]),
    20: call("vsm_color", "sets the marker colour", [vi("index", "colour index", { values: DEFAULT_PALETTE })]),
    21: call("vst_font", "selects a text font", [vi("font", "font id, 1 for the system font")]),
    22: call("vst_color", "sets the text colour", [vi("index", "colour index", { values: DEFAULT_PALETTE })]),
    23: call("vsf_interior", "sets the fill interior", [vi("style", "0 hollow, 1 solid, 2 pattern, 3 hatch, 4 user defined")]),
    24: call("vsf_style", "sets the fill pattern or hatch index", [vi("style", "1 to 24 for patterns, 1 to 12 for hatches")]),
    25: call("vsf_color", "sets the fill colour", [vi("index", "colour index", { values: DEFAULT_PALETTE })]),
    26: call("vq_color", "reads a colour index's components", [vi("index", "colour index", { values: DEFAULT_PALETTE }), vi("flag", "0 requested values, 1 actual values")]),
    27: call("vq_cellarray", "reads a cell array", [pt("xy", "rectangle corners")]),
    28: call("vrq_locator", "waits for a locator (mouse) position", [pt("x", "initial x"), pt("y", "initial y")]),
    29: call("vrq_valuator", "waits for a valuator change", [vi("initial", "initial value")]),
    30: call("vrq_choice", "waits for a choice device", [vi("initial", "initial choice")]),
    31: call("vrq_string", "waits for a string from the keyboard", [vi("length", "maximum length"), vi("echo", "0 no echo, 1 echo"), pt("x", "echo x"), pt("y", "echo y")]),
    32: call("vswr_mode", "sets the writing mode", [vi("mode", "writing mode", { values: VDI_WRITING_MODES })]),
    33: call("vsin_mode", "sets an input device to request or sample mode", [vi("device", "1 locator, 2 valuator, 3 choice, 4 string"), vi("mode", "1 request, 2 sample")]),
    35: call("vql_attributes", "reads the line attributes"),
    36: call("vqm_attributes", "reads the marker attributes"),
    37: call("vqf_attributes", "reads the fill attributes"),
    38: call("vqt_attributes", "reads the text attributes"),
    39: call("vst_alignment", "sets horizontal and vertical text alignment", [vi("horizontal", "0 left, 1 centre, 2 right"), vi("vertical", "0 baseline, 1 half, 2 ascent, 3 bottom, 4 descent, 5 top")]),
    100: call("v_opnvwk", "opens a virtual workstation on the screen and returns its handle", [vi("work_in", "eleven words, as v_opnwk; contrl[6] holds the physical handle")]),
    101: call("v_clsvwk", "closes a virtual workstation"),
    102: call("vq_extnd", "reads extended workstation information", [vi("flag", "0 v_opnwk values, 1 extended values")]),
    103: call("v_contourfill", "flood fills from a point up to a colour", [pt("x", "x"), pt("y", "y"), vi("colour", "boundary colour, or -1 to fill the same colour")]),
    104: call("vsf_perimeter", "switches the fill outline on or off", [vi("flag", "0 off, 1 on")]),
    105: call("v_get_pixel", "reads one pixel's value and colour index", [pt("x", "x"), pt("y", "y")]),
    106: call("vst_effects", "sets text effects", [vi("effects", "bit 0 bold, 1 light, 2 italic, 3 underline, 4 outline, 5 shadow")]),
    107: call("vst_point", "sets the text size in points", [vi("points", "point size")]),
    108: call("vsl_ends", "sets the line end styles", [vi("begin", "0 square, 1 arrow, 2 round"), vi("end", "0 square, 1 arrow, 2 round")]),
    109: call("vro_cpyfm", "copies a raster block in opaque mode", [vi("mode", "logic operation 0 to 15; 3 is replace"), pt("xy", "source and destination rectangles"), c("7", "source MFDB pointer"), c("9", "destination MFDB pointer")]),
    110: call("vr_trnfm", "transforms a raster between device and standard form", [c("7", "source MFDB pointer"), c("9", "destination MFDB pointer")]),
    111: call("vsc_form", "defines the mouse cursor form", [vi("form", "37 words: hot spot, reserved, colours, mask, data")]),
    112: call("vsf_udpat", "defines a user fill pattern", [vi("pattern", "16 words per plane"), c("3", "number of words")]),
    113: call("vsl_udsty", "defines a user line style", [vi("pattern", "16-bit pattern")]),
    114: call("vr_recfl", "fills a rectangle without an outline", [pt("xy", "two corners")]),
    115: call("vqin_mode", "reads an input device's mode", [vi("device", "1 locator, 2 valuator, 3 choice, 4 string")]),
    116: call("vqt_extent", "measures a string's bounding box", [vi("string", "characters as words")]),
    117: call("vqt_width", "measures one character's width", [vi("char", "character", { type: "character" })]),
    118: call("vex_timv", "installs a timer tick handler", [c("7", "new handler")]),
    119: call("vst_load_fonts", "loads the GDOS fonts", [vi("select", "reserved, 0")], { requires: "GDOS" }),
    120: call("vst_unload_fonts", "unloads the GDOS fonts", [vi("select", "reserved, 0")], { requires: "GDOS" }),
    121: call("vrt_cpyfm", "copies a monochrome raster in transparent mode with two colours", [vi("mode", "writing mode", { values: VDI_WRITING_MODES }), vi("foreground", "colour index", { values: DEFAULT_PALETTE }), vi("background", "colour index", { values: DEFAULT_PALETTE }), pt("xy", "source and destination rectangles")]),
    122: call("v_show_c", "shows the mouse cursor", [vi("reset", "0 unconditionally, 1 only if hidden once")]),
    123: call("v_hide_c", "hides the mouse cursor"),
    124: call("vq_mouse", "reads the mouse position and buttons"),
    125: call("vex_butv", "installs a mouse button handler", [c("7", "new handler")]),
    126: call("vex_motv", "installs a mouse movement handler", [c("7", "new handler")]),
    127: call("vex_curv", "installs a mouse cursor draw handler", [c("7", "new handler")]),
    128: call("vq_key_s", "reads the shift key state"),
    129: call("vs_clip", "sets or clears the clipping rectangle", [vi("flag", "0 off, 1 on"), pt("xy", "two corners")]),
    130: call("vqt_name", "returns a font's name and id", [vi("element", "font number, from 1")]),
    131: call("vqt_fontinfo", "returns the current font's metrics"),
  });

  const LINE_A = Object.freeze({
    0xA000: call("Line-A init", "initialises Line-A and returns the variable table in A0 and D0, the font headers in A1 and the routine table in A2"),
    0xA001: call("put pixel", "sets one pixel from INTIN[0] at PTSIN[0], PTSIN[1]"),
    0xA002: call("get pixel", "reads the pixel at PTSIN[0], PTSIN[1] into D0"),
    0xA003: call("line", "draws a line from X1, Y1 to X2, Y2 with the current pattern and mode"),
    0xA004: call("horizontal line", "draws a horizontal line from X1 to X2 on Y1 with the fill pattern"),
    0xA005: call("filled rectangle", "fills the rectangle X1, Y1 to X2, Y2 with the fill pattern"),
    0xA006: call("filled polygon", "fills one scan line of the polygon in PTSIN"),
    0xA007: call("bitblt", "performs a bit block transfer described by the BITBLT structure in A6"),
    0xA008: call("textblt", "draws one character with the text parameters in the Line-A variables"),
    0xA009: call("show mouse", "shows the mouse cursor"),
    0xA00A: call("hide mouse", "hides the mouse cursor"),
    0xA00B: call("transform mouse", "installs a new mouse form from the MFORM in INTIN"),
    0xA00C: call("undraw sprite", "restores the background saved when a sprite was drawn; A2 points at the save block"),
    0xA00D: call("draw sprite", "draws a sprite at D0, D1; A0 points at the sprite definition and A2 at its save block"),
    0xA00E: call("copy raster", "copies a raster block using the parameters in the Line-A variables"),
    0xA00F: call("seedfill", "flood fills from PTSIN[0], PTSIN[1] using the fill pattern"),
  });

  const TRAPS = Object.freeze({
    1: { name: "GEMDOS", table: GEMDOS },
    13: { name: "BIOS", table: BIOS },
    14: { name: "XBIOS", table: XBIOS },
  });

  // ------------------------------------------------------------ formatting

  // A value is read as a number and written as a number, so both forms are
  // shown: the decimal the source used and the hexadecimal an ST reference
  // documents the field in.
  function formatValue(value) {
    if (value == null) return "unknown";
    if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
    const magnitude = Math.abs(value).toString(16).toUpperCase();
    return `${value} (${value < 0 ? "-" : ""}$${magnitude})`;
  }

  function valueText(spec, value) {
    const shown = formatValue(value);
    if (spec.values) {
      const known = spec.values[String(value)];
      return known ? `${shown}: ${known}` : `${shown}: ${spec.otherwise || "an undocumented or system-specific value"}`;
    }
    if (spec.bits) {
      const set = spec.bits.map(bit => ((value & bit.mask) ? bit.set : bit.clear)).filter(Boolean);
      return `${shown}: ${set.join("; ") || "no bits set"}`;
    }
    if (spec.unit) return `${shown} ${spec.unit}${Math.abs(value) === 1 ? "" : "s"}`;
    if (spec.type === "character" && value >= 32 && value <= 126) return `${shown} ('${String.fromCharCode(value)}')`;
    return shown;
  }

  function stackOffsets(specs) {
    let offset = 2;
    return (specs || []).map(spec => {
      const label = `${offset}(sp).${spec.size}`;
      offset += spec.size === "l" ? 4 : 2;
      return { ...spec, offset: label };
    });
  }

  function stackValue(stack, index, offset) {
    if (Array.isArray(stack)) return stack[index];
    if (stack && typeof stack === "object") {
      const bare = offset.replace(/\.[wl]$/, "");
      return stack[offset] ?? stack[bare] ?? stack[index];
    }
    return undefined;
  }

  function describeStackParameters(specs, stack) {
    return stackOffsets(specs).map((spec, index) => {
      const value = stackValue(stack, index, spec.offset);
      const proved = value != null && typeof value === "number";
      const text = proved
        ? `${spec.offset} ${spec.name} = ${valueText(spec, value)}${spec.values || spec.bits ? "" : ` (${spec.meaning})`}`
        : `${spec.offset} ${spec.name}: ${spec.meaning}, not proved on this path`;
      return { offset: spec.offset, name: spec.name, meaning: spec.meaning, value: proved ? value : null, text };
    });
  }

  function arrayIndexes(specs) {
    const counters = {};
    return (specs || []).map(spec => {
      const explicit = spec.array === "contrl" ? Number(spec.name) : null;
      const index = explicit ?? (counters[spec.array] = (counters[spec.array] ?? -1) + 1);
      return { ...spec, slot: `${spec.array}[${index}]`, index };
    });
  }

  function describeArrayParameters(specs, values = {}) {
    return arrayIndexes(specs).map(spec => {
      const source = values[spec.array];
      const value = Array.isArray(source) ? source[spec.index] : undefined;
      const proved = typeof value === "number";
      const label = spec.array === "contrl" ? `${spec.slot}` : `${spec.slot} ${spec.name}`;
      const text = proved
        ? `${label} = ${valueText(spec, value)}${spec.values || spec.bits ? "" : ` (${spec.meaning})`}`
        : `${label}: ${spec.meaning}`;
      return { slot: spec.slot, name: spec.name, meaning: spec.meaning, value: proved ? value : null, text };
    });
  }

  function result(name, summary, parameters, spec = {}, extra = {}) {
    const warnings = [...(extra.warnings || [])];
    if (spec.requires) warnings.push(`Requires ${spec.requires}.`);
    const details = parameters.map(parameter => parameter.text);
    return {
      name,
      summary,
      parameters,
      warnings,
      details,
      platforms: spec.platforms || DEFAULT_MACHINES,
      requires: spec.requires || extra.requires || "",
      ...(spec.result ? { result: spec.result } : {}),
    };
  }

  // ----------------------------------------------------------- explainers

  function explainTrapCall(trap, number, stack) {
    const family = TRAPS[Number(trap)];
    if (!family) {
      return result(`TRAP #${trap}`, `raises TRAP #${trap}, which TOS does not define; a program or resident utility must have installed the vector`, [], {}, { requires: "the vector installed by the program" });
    }
    const key = Number(number);
    const spec = Number.isFinite(key) ? family.table[key] : null;
    if (!spec) {
      return result(
        `${family.name} ${Number.isFinite(key) ? formatValue(key) : "call"}`,
        `${family.name} function ${Number.isFinite(key) ? formatValue(key) : "with an unproved number"}, which is not in this catalogue`,
        [],
        {},
        { warnings: ["An unknown function number returns EINVFN (-32) on a plain TOS; MiNT and MagiC add functions above the TOS range."], requires: `the ${family.name} reference for this function number` },
      );
    }
    return result(spec.name, `${family.name} ${formatValue(key)} ${spec.name}: ${spec.summary}`, describeStackParameters(spec.parameters, stack), spec);
  }

  const explainGemdosCall = (number, stack) => explainTrapCall(1, number, stack);
  const explainBiosCall = (number, stack) => explainTrapCall(13, number, stack);
  const explainXbiosCall = (number, stack) => explainTrapCall(14, number, stack);

  function explainAesCall(opcode, control, intIn) {
    const key = Number(opcode);
    const spec = AES[key];
    if (!spec) {
      return result(`AES ${formatValue(key)}`, `AES function ${formatValue(key)}, which is not in this catalogue`, [], {}, { requires: "the AES reference for this opcode" });
    }
    const values = { int_in: Array.isArray(intIn) ? intIn : [], addr_in: Array.isArray(control?.addr_in) ? control.addr_in : [] };
    const parameters = describeArrayParameters(spec.parameters, values);
    const warnings = [];
    if (Array.isArray(control) && control.length >= 5) {
      warnings.push(`control[1..4] declare ${control[1]} int_in, ${control[2]} int_out, ${control[3]} addr_in and ${control[4]} addr_out words.`);
    }
    return result(spec.name, `AES ${formatValue(key)} ${spec.name}: ${spec.summary}`, parameters, spec, { warnings });
  }

  function explainVdiCall(opcode, subOpcode, values = {}) {
    const key = Number(opcode);
    const entry = VDI[key];
    if (!entry) {
      return result(`VDI ${formatValue(key)}`, `VDI function ${formatValue(key)}, which is not in this catalogue`, [], {}, { requires: "the VDI reference for this opcode" });
    }
    if (entry.subfunctions) {
      const sub = Number(subOpcode);
      const spec = entry.subfunctions[sub];
      if (!spec) {
        return result(`VDI ${key}/${Number.isFinite(sub) ? sub : "?"}`, `VDI ${entry.name} ${Number.isFinite(sub) ? formatValue(sub) : "with an unproved contrl[5]"}, which is not in this catalogue`, [], {}, { requires: `the VDI reference for ${entry.name} ${Number.isFinite(sub) ? sub : ""}`.trim() });
      }
      return result(spec.name, `VDI ${key}/${sub} ${spec.name}: ${spec.summary}`, describeArrayParameters(spec.parameters, values), spec);
    }
    return result(entry.name, `VDI ${formatValue(key)} ${entry.name}: ${entry.summary}`, describeArrayParameters(entry.parameters, values), entry);
  }

  function explainLineA(opcode) {
    const key = Number(opcode);
    const spec = LINE_A[key];
    if (!spec) {
      return result(`$${Number.isFinite(key) ? key.toString(16).toUpperCase() : "A???"}`, "a Line-A opcode that is not in this catalogue", [], {}, { requires: "the Line-A reference" });
    }
    return result(spec.name, `Line-A $${key.toString(16).toUpperCase()} ${spec.name}: ${spec.summary}`, [], spec, {
      warnings: ["Line-A bypasses the VDI and is not supported by every TOS or AES replacement; it is fast on an ST and unreliable elsewhere."],
    });
  }

  // GEM reached through TRAP #2: D0 selects the AES or the VDI and D1 points
  // at the parameter block.
  function explainGemTrap(d0, opcode, subOpcode) {
    const selector = Number(d0);
    if (selector === 0xC8) return explainAesCall(opcode);
    if (selector === 0x73) return explainVdiCall(opcode, subOpcode);
    if (selector === -1 || selector === 0xFFFFFFFF) return result("GEM query", "TRAP #2 with D0 = -1 asks whether GEM is present; D0 returns a pointer to the dispatcher when it is", [], {});
    return result("TRAP #2", `TRAP #2 with D0 = ${formatValue(selector)}, which is neither the AES ($C8) nor the VDI ($73)`, [], {}, { requires: "D0 = $C8 for the AES or $73 for the VDI" });
  }

  // BASIC statements that reach the same traps. GFA BASIC wraps each one in a
  // function whose first argument is the function number; STOS has the same
  // three functions; ST BASIC reaches GEM through GEMSYS and VDISYS with the
  // opcode already in the parameter arrays.
  const BASIC_CALLS = Object.freeze({
    GEMDOS: { family: "gemdos", summary: "calls a GEMDOS function through TRAP #1; the first argument is the function number and the rest are pushed as words, or as longs when prefixed with L:" },
    BIOS: { family: "bios", summary: "calls a BIOS function through TRAP #13; the first argument is the function number" },
    XBIOS: { family: "xbios", summary: "calls an XBIOS function through TRAP #14; the first argument is the function number" },
    GEMSYS: { family: "aes", summary: "calls an AES function through TRAP #2 with the opcode in GINTIN/CONTRL(0) and the parameter block GFA and ST BASIC keep for it" },
    VDISYS: { family: "vdi", summary: "calls a VDI function through TRAP #2 with the opcode in CONTRL(0) and the current INTIN and PTSIN arrays" },
    PEEK: { summary: "reads one byte from an address", parameters: [{ name: "address", meaning: "byte address" }] },
    DPEEK: { summary: "reads one word from an even address", parameters: [{ name: "address", meaning: "word address, which must be even" }] },
    LPEEK: { summary: "reads one long from an even address", parameters: [{ name: "address", meaning: "long address, which must be even" }] },
    POKE: { summary: "writes one byte to an address", parameters: [{ name: "address", meaning: "byte address" }, { name: "value", meaning: "byte to write" }] },
    DPOKE: { summary: "writes one word to an even address", parameters: [{ name: "address", meaning: "word address, which must be even" }, { name: "value", meaning: "word to write" }] },
    LPOKE: { summary: "writes one long to an even address", parameters: [{ name: "address", meaning: "long address, which must be even" }, { name: "value", meaning: "long to write" }] },
    VSYNC: { summary: "waits for the next vertical blank, like XBIOS 37 Vsync" },
    SETCOLOR: { summary: "sets one palette register through XBIOS 7 Setcolor", parameters: [{ name: "index", meaning: "palette register", values: HARDWARE_PALETTE }, { name: "colour", meaning: "$RGB value with 3 bits per component on an ST, 4 on an STE" }] },
    SOUND: { summary: "programs one voice of the YM2149 sound chip", parameters: [{ name: "voice", meaning: "1 to 3" }, { name: "volume", meaning: "0 to 15" }, { name: "note", meaning: "1 to 12, or 0 for a period" }, { name: "octave", meaning: "1 to 8, or a period value when note is 0" }, { name: "duration", meaning: "fiftieths of a second, -1 for immediate" }] },
    WAVE: { summary: "sets the YM2149 envelope and noise mixer", parameters: [{ name: "voices", meaning: "bit mask of voices the envelope shapes" }, { name: "envelope", meaning: "bit mask of voices using the envelope" }, { name: "shape", meaning: "envelope shape 0 to 15" }, { name: "period", meaning: "envelope period" }, { name: "duration", meaning: "fiftieths of a second" }] },
  });

  function explainBasicCall(name, values) {
    const spec = BASIC_CALLS[String(name || "").toUpperCase()];
    if (!spec) return null;
    const list = Array.isArray(values) ? values : [];
    if (spec.family) {
      const [number, ...rest] = list;
      let inner;
      if (spec.family === "gemdos") inner = explainGemdosCall(number, rest);
      else if (spec.family === "bios") inner = explainBiosCall(number, rest);
      else if (spec.family === "xbios") inner = explainXbiosCall(number, rest);
      else if (spec.family === "aes") inner = number == null ? null : explainAesCall(number);
      // GFA VDISYS opcode,vertices,intin,sub-opcode: the sub-opcode is the
      // fourth argument, mirroring contrl[0], contrl[1], contrl[3], contrl[5].
      else inner = number == null ? null : explainVdiCall(number, rest[2]);
      if (!inner) {
        return { name: String(name).toUpperCase(), summary: spec.summary, parameters: [], warnings: ["The opcode comes from the parameter block rather than the statement, so it was not proved here."], details: [], platforms: DEFAULT_MACHINES, requires: "" };
      }
      return { ...inner, summary: `${spec.summary}. ${inner.summary}` };
    }
    const parameters = (spec.parameters || []).map((parameter, index) => {
      const value = list[index];
      const proved = typeof value === "number";
      return {
        name: parameter.name, meaning: parameter.meaning, value: proved ? value : null,
        text: proved ? `${parameter.name} = ${valueText(parameter, value)}${parameter.values ? "" : ` (${parameter.meaning})`}` : `${parameter.name}: ${parameter.meaning}`,
      };
    });
    return { name: String(name).toUpperCase(), summary: spec.summary, parameters, warnings: [], details: parameters.map(item => item.text), platforms: DEFAULT_MACHINES, requires: "" };
  }

  // Names for the editor: a function name found in source, such as Fopen or
  // v_opnvwk, resolved back to its family and number.
  const NAMES = (() => {
    const index = new Map();
    const add = (family, number, spec) => { if (spec?.name) index.set(spec.name.toUpperCase(), { family, number, spec }); };
    for (const [number, spec] of Object.entries(GEMDOS)) add("GEMDOS", Number(number), spec);
    for (const [number, spec] of Object.entries(BIOS)) add("BIOS", Number(number), spec);
    for (const [number, spec] of Object.entries(XBIOS)) add("XBIOS", Number(number), spec);
    for (const [number, spec] of Object.entries(AES)) add("AES", Number(number), spec);
    for (const [number, spec] of Object.entries(VDI)) {
      if (spec.subfunctions) for (const [sub, inner] of Object.entries(spec.subfunctions)) add("VDI", `${number}/${sub}`, inner);
      else add("VDI", Number(number), spec);
    }
    return index;
  })();

  function lookupName(name) {
    return NAMES.get(String(name || "").toUpperCase()) || null;
  }

  return Object.freeze({
    DEFAULT_MACHINES,
    GEMDOS,
    BIOS,
    XBIOS,
    AES,
    VDI,
    LINE_A,
    TRAPS,
    FOPEN_MODES,
    FSEEK_MODES,
    ATTRIBUTE_BITS,
    PEXEC_MODES,
    GETREZ_VALUES,
    RWABS_FLAGS,
    SUPER_ARGUMENTS,
    BCONOUT_DEVICES,
    MEDIACH_RESULTS,
    FORM_ALERT_ICONS,
    EVNT_MULTI_FLAGS,
    AES_OBJECT_TYPES,
    VDI_WRITING_MODES,
    DEFAULT_PALETTE,
    HARDWARE_PALETTE,
    BASIC_CALLS,
    explainTrapCall,
    explainGemdosCall,
    explainBiosCall,
    explainXbiosCall,
    explainAesCall,
    explainVdiCall,
    explainLineA,
    explainGemTrap,
    explainBasicCall,
    formatValue,
    lookupName,
  });
})();

if (typeof module !== "undefined") module.exports = window.AtariCallCatalogue;
