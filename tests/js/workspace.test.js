"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function load(relativePath, exportName) {
  const context = vm.createContext({ window: {} });
  const source = fs.readFileSync(path.join(__dirname, "../..", relativePath), "utf8");
  vm.runInContext(source, context, { filename: relativePath });
  return context.window[exportName];
}

function test(name, callback) {
  try { callback(); process.stdout.write(`ok - ${name}\n`); }
  catch (error) { process.stderr.write(`not ok - ${name}\n${error.stack}\n`); process.exitCode = 1; }
}

const workspace = load("app/static/workspace.js", "AtariWorkspace");
const visuals = load("app/static/file-visuals.js", "AtariFileVisuals");
const imports = load("app/static/import-planning.js", "AtariImportPlanning");
const metadata = load("app/static/atari-metadata.js", "AtariMetadata");
const help = load("app/static/help.js", "AtariHelp");
const about = load("app/static/about.js", "AtariAbout");
const editorWorkspace = load("app/static/editor-workspace.js", "AtariEditorWorkspace");
const identifiers = load("app/static/identifiers.js", "AtariIdentifiers");
const operationUI = load("app/static/operation-ui.js", "AtariOperationUI");
const workspacePersistence = load("app/static/workspace-persistence.js", "AtariWorkspacePersistence");
const paneWindows = load("app/static/pane-window-manager.js", "AtariPaneWindowManager");
const paneView = load("app/static/pane-view.js", "AtariPaneView");
const transferPlanning = load("app/static/transfer-planning.js", "AtariTransferPlanning");

test("workspace pane state has one canonical initial shape", () => {
  const pane = workspace.newPaneState({ kind: "hd", doubleSided: false });
  // A GEMDOS volume root is the empty path, written C:\ when a drive
  // letter is known.
  assert.equal(pane.path, "");
  assert.equal(pane.menuDetectionPending, true);
  assert.deepEqual(Array.from(pane.selection), []);
  assert.equal(pane.windowState, null);
});

test("workspace paths follow the GEMDOS grammar and accept a forward slash on input", () => {
  assert.deepEqual(Array.from(workspace.splitPath("C:\\GAMES\\ELITE")), ["GAMES", "ELITE"]);
  assert.deepEqual(Array.from(workspace.splitPath("GAMES/ELITE")), ["GAMES", "ELITE"]);
  assert.deepEqual(Array.from(workspace.splitPath("C:\\")), []);
  assert.deepEqual(Array.from(workspace.splitPath("$")), []);
  assert.equal(workspace.fullPath("GAMES", "ELITE.PRG"), "GAMES\\ELITE.PRG");
  assert.equal(workspace.fullPath("", "AUTO"), "AUTO");
  assert.equal(workspace.parentPath("GAMES\\ELITE\\DATA"), "GAMES\\ELITE");
  assert.equal(workspace.parentPath("AUTO"), "");
  assert.equal(workspace.drivePath("c", "GAMES\\ELITE"), "C:\\GAMES\\ELITE");
  assert.equal(workspace.drivePath("A", ""), "A:\\");
  assert.equal(workspace.restoredGemdosPath({ path: "$" }), "");
  assert.equal(workspace.isGemdosPane({ image: { kind: "gemdos" } }), true);
  assert.equal(workspace.isGemdosPane({ image: { kind: "hd" }, partition: 0 }), true);
  assert.equal(workspace.isGemdosPane({ image: { kind: "hd" }, partition: null }), false);
  assert.equal(workspace.normalisePage("$0007"), "7");
});

test("pane window geometry supports sides, corners and constrained free placement", () => {
  const bounds = { width: 1200, height: 800 };
  assert.deepEqual({ ...paneWindows.snapGeometry("left", bounds) }, { x: 0, y: 0, width: 600, height: 800 });
  assert.deepEqual({ ...paneWindows.snapGeometry("bottom-right", bounds) }, { x: 600, y: 400, width: 600, height: 400 });
  assert.equal(paneWindows.snapTarget({ x: 4, y: 5 }, bounds), "top-left");
  assert.equal(paneWindows.snapTarget({ x: 1198, y: 410 }, bounds), "right");
  assert.deepEqual(
    { ...paneWindows.constrainGeometry({ x: 1100, y: -20, width: 800, height: 900 }, bounds) },
    { x: 400, y: 0, width: 800, height: 800 },
  );
});

test("workspace selection helpers preserve unique stable keys", () => {
  const pane = workspace.newPaneState();
  workspace.setSelection(pane, ["3", "3", "4"]);
  assert.deepEqual(Array.from(workspace.selectionKeys(pane)), ["3", "4"]);
  assert.equal(pane.selected, null);
});

test("file visuals classify ST content consistently before rendering", () => {
  const pane = workspace.newPaneState({ kind: "gemdos" });
  const kindOf = (name, archive = false) => visuals.entryIcon(pane, { name }, "file", archive, false).kind;
  assert.equal(kindOf("DESKTOP.INF"), "script");
  assert.equal(kindOf("NEWDESK.INF"), "script");
  assert.equal(kindOf("EMUDESK.INF"), "script");
  assert.equal(kindOf("MINT.CNF"), "script");
  assert.equal(kindOf("AHDI.SYS"), "script");
  assert.equal(kindOf("GAME.GFA"), "basic");
  assert.equal(kindOf("GAME.BAS"), "basic");
  assert.equal(kindOf("GAME.LST"), "basic");
  assert.equal(kindOf("GAME.PRG"), "binary");
  assert.equal(visuals.entryIcon(pane, { name: "GAME.PRG" }, "file", false, false).label, "GEMDOS program");
  assert.equal(kindOf("READ.ME"), "text");
  assert.equal(kindOf("MANUAL.TXT"), "text");
  assert.equal(kindOf("GAME.ZIP", true), "archive");
  assert.equal(kindOf("DISK.MSA"), "archive");
  assert.equal(kindOf("DISK.ST"), "archive");
  assert.equal(kindOf("PICTURE.PI1"), "file");
  assert.equal(visuals.entryIcon(pane, { name: "PICTURE.PI1" }, "file", false, false).label, "Picture");
  assert.equal(visuals.entryIcon(pane, { name: "TUNE.SNDH" }, "file", false, false).label, "Music or sample");
  assert.equal(visuals.entryIcon(pane, { name: "DESKTOP.RSC" }, "file", false, false).label, "System or resource file");
  assert.equal(visuals.entryIcon(pane, { name: "AUTO" }, "dir", false, false).kind, "folder");
  assert.ok(visuals.scriptNamePattern.test("DESKTOP.INF"));
  assert.ok(visuals.scriptNamePattern.test("anything.cnf"));
});

test("import planning applies GEMDOS 8.3 limits without UI state", () => {
  const rule = imports.targetNameRule({ image: { kind: "gemdos" } }, "READ.ME");
  assert.equal(rule.suggested, "READ.ME");
  assert.equal(rule.valid, true);
  assert.equal(rule.limit, 12);
  assert.equal(rule.label, "GEMDOS 8.3");
  // Lower case is written upper case, so a host name is adjusted but not
  // truncated.
  const lower = imports.targetNameRule({ image: { kind: "gemdos" } }, "Elite.prg");
  assert.equal(lower.valid, false);
  assert.equal(lower.suggested, "ELITE.PRG");
  assert.equal(lower.truncated, false);
  // A long stem is cut to eight characters and a long extension to three.
  const longRule = imports.targetNameRule({ image: { kind: "gemdos" } }, "A descriptive filename.document");
  assert.equal(longRule.valid, false);
  assert.equal(longRule.suggested, "A_DESCRI.DOC");
  assert.equal(longRule.truncated, true);
  // Only the last full stop separates the extension; earlier ones cannot
  // be stored.
  assert.equal(imports.targetNameRule({ image: { kind: "gemdos" } }, "OS-V3.5.TXT").suggested, "OS-V3_5.TXT");
  // The forbidden characters and a space are replaced.
  assert.equal(imports.targetNameRule({ image: { kind: "gemdos" } }, "Games/Elite").suggested, "ELITE");
  assert.equal(imports.targetNameRule({ image: { kind: "gemdos" } }, "a b:c*d?e.txt").suggested, "A_B_C_D_.TXT");
  assert.equal(imports.targetNameRule({ image: { kind: "gemdos" } }, "Elite🙂").suggested, "ELITE_");
  assert.equal(imports.targetNameRule({ image: { kind: "gemdos" } }, "CAFÉ.TXT").valid, true);
  // Unique names carry a numeric suffix inside the eight characters.
  const unique = imports.uniqueGemdosNames([
    { name: "LongFilename1.txt", path: "Pack/LongFilename1.txt" },
    { name: "LongFilename2.txt", path: "Pack/LongFilename2.txt" },
    { name: "longfilename3.txt", path: "Pack/longfilename3.txt" },
  ]);
  assert.deepEqual(Array.from(unique, item => item.targetName), ["LONGFILE.TXT", "LONGFIL1.TXT", "LONGFIL2.TXT"]);
  assert.equal(unique[0].prefix, "Pack");
});

test("import planning fills TOS floppies by cluster and root entry count", () => {
  // A 720 KiB disk has 711 data clusters of 1 KiB once the boot sector,
  // two FATs and the root directory are taken off.
  const disks = imports.allocateFilesToDisks([
    { name: "ONE", length: 400 * 1024 },
    { name: "TWO", length: 400 * 1024 },
  ], "720k");
  assert.equal(disks.length, 2);
  const together = imports.allocateFilesToDisks([
    { name: "ONE", length: 100 },
    { name: "TWO", length: 200 },
  ], "720k");
  assert.equal(together.length, 1);
  assert.equal(together[0].files.length, 2);
  // The same pair fits one 880 KiB disk.
  assert.equal(imports.allocateFilesToDisks([{ name: "ONE", length: 400 * 1024 }, { name: "TWO", length: 400 * 1024 }], "880k").length, 1);
  // A 1.44 MiB disk holds more clusters and 224 root entries.
  assert.equal(imports.allocateFilesToDisks([{ name: "BIG", length: 1400 * 1024 }], "1440k").length, 1);
  assert.throws(() => imports.allocateFilesToDisks([{ name: "BIG", length: 800 * 1024 }], "720k"), /too large/);
  const many = imports.allocateFilesToDisks(Array.from({ length: 113 }, (_unused, index) => ({ name: `F${index}`, length: 10 })), "720k");
  assert.equal(many.length, 2);
});

test("attributes from a sidecar are accepted in either written form", () => {
  // The six letters are kept verbatim, because that is the form a person
  // can check at a glance.
  assert.equal(imports.normaliseAttributes("-----a"), "-----a");
  assert.equal(imports.normaliseAttributes("r---da"), "r---da");
  // A raw byte is normalised so one written value means one number.
  assert.equal(imports.normaliseAttributes("$20"), "0x20");
  assert.equal(imports.normaliseAttributes("0x20"), "0x20");
  assert.equal(imports.normaliseAttributes("&H01"), "0x01");
  // Anything else is reported as absent rather than guessed at.
  assert.equal(imports.normaliseAttributes("read-only"), "");
});

test("the GEMDOS attribute byte round trips through six plain letters", () => {
  assert.equal(metadata.ATTRIBUTE_LETTERS, "rhsvda");
  // A normal file with the archive bit set.
  assert.equal(metadata.formatAttributes(0x20), "-----a");
  // A read-only hidden system file, the state of a TOS boot file.
  assert.equal(metadata.formatAttributes(0x07), "rhs---");
  assert.equal(metadata.formatAttributes(0), "------");
  assert.deepEqual({ ...metadata.attributeFlags(0x10) }, { r: false, h: false, s: false, v: false, d: true, a: false });
  assert.equal(metadata.attributeValue("r---da"), 0x31);
  assert.equal(metadata.attributeValue(metadata.attributeFlags(0x25)), 0x25);
  assert.equal(metadata.attributeHex(metadata.attributeFlags(0x01)), "0x01");
  assert.equal(metadata.attributeHex("-----a"), "0x20");
  assert.equal(metadata.parseAttributes("$20"), 0x20);
  assert.equal(metadata.parseAttributes("32"), 0x20);
  assert.equal(metadata.parseAttributes("-----a"), 0x20);
  assert.equal(metadata.parseAttributes("nonsense"), null);
});

test("GEMDOS date and time stamps convert to and from ISO text at two-second resolution", () => {
  const stamp = metadata.parseDatestamp("1985-06-20T14:30:03");
  assert.equal(stamp.date, ((1985 - 1980) << 9) | (6 << 5) | 20);
  assert.equal(stamp.time, (14 << 11) | (30 << 5) | 1);
  assert.equal(metadata.formatDatestamp(stamp), "1985-06-20T14:30:02");
  assert.equal(metadata.formatDatestamp(stamp.date, stamp.time), "1985-06-20T14:30:02");
  assert.equal(metadata.formatDatestamp(0x0021, 0), "1980-01-01T00:00:00");
  assert.equal(metadata.parseDatestamp("1979-12-31"), null);
  assert.equal(metadata.parseDatestamp("not a date"), null);
});

test("help handbook is isolated behind an injected modal boundary", () => {
  const showHelp = help.create({ showModal() {}, modalContent: {} });
  assert.equal(typeof showHelp, "function");
});

test("the application header exposes handbook and about help actions", () => {
  const markup = fs.readFileSync(path.join(__dirname, "../../app/static/index.html"), "utf8");
  assert.match(markup, /id="helpMenu"/);
  assert.match(markup, /id="helpGuideButton"/);
  assert.match(markup, /id="aboutButton"/);
});

test("about content uses runtime version and host metadata", () => {
  let markup = "";
  const showAbout = about.create({
    showModal(value) { markup = value; },
    esc: value => String(value),
    context: () => ({ version: "1.2.3", engine: "atarinut", host: "desktop" }),
  });
  showAbout();
  assert.match(markup, /Version 1\.2\.3/);
  assert.match(markup, /Linux desktop application/);
  assert.match(markup, /Third-party notices/);
});

test("editor workspace persistence validates, limits and restores documents", () => {
  const values = new Map();
  const storage = {
    getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
  const manager = editorWorkspace.create({ storage, key: "editors", maxDocuments: 2, maxDraftBytes: 4, maxPanes: 3 });
  manager.state.documents.set("one", { key: "one", imageId: "a".repeat(32), index: 0, path: "ONE", name: "ONE", draft: "123456" });
  manager.state.documents.set("two", { key: "two", imageId: "b".repeat(32), index: 1, path: "TWO", name: "TWO" });
  manager.state.active = "one";
  manager.persist();

  const restored = editorWorkspace.create({ storage, key: "editors", maxDocuments: 2, maxDraftBytes: 4, maxPanes: 3 });
  restored.restore();
  assert.equal(restored.state.documents.get("one").draft, "1234");
  assert.equal(restored.state.restoreCandidate, "one");
});

test("operation lifecycle is isolated behind an injected pane controller", () => {
  const controller = operationUI.create({
    panes: [], api() {}, setLoading() {}, renderPane() {},
    modal: { open: false }, setModalAbort() {}, setModalProgress() {},
    newUuid: () => "00000000-0000-4000-8000-000000000000",
  });
  assert.equal(typeof controller.guardedPaneAction, "function");
  assert.equal(typeof controller.trackedPaneOperation, "function");
});

test("operation identifiers use the browser UUID implementation when available", () => {
  assert.equal(identifiers.newUuid({ randomUUID: () => "native-uuid" }), "native-uuid");
});

test("operation identifiers remain available on non-secure HTTP origins", () => {
  const cryptoSource = {
    getRandomValues(bytes) {
      bytes.fill(0);
      return bytes;
    },
  };
  assert.equal(identifiers.newUuid(cryptoSource), "00000000-0000-4000-8000-000000000000");
});

test("operation identifiers fail explicitly on obsolete browsers without Web Crypto", () => {
  assert.throws(
    () => identifiers.newUuid({}),
    /cannot create secure operation identifiers/i,
  );
});

test("workspace recovery is isolated behind an injected persistence controller", () => {
  const controller = workspacePersistence.create({
    panes: [], storage: { getItem() { return null; }, setItem() {} },
    storageKey: "workspace", newPaneState() { return {}; },
    restoredGemdosPath() { return ""; }, api() {}, rebuildPaneHosts() {},
    renderPane() {}, acceptImage() {}, loadDirectory() {},
    editorWorkspace: { state: {} }, activateEditorDocument() {}, toast() {},
  });
  assert.equal(typeof controller.remember, "function");
  assert.equal(typeof controller.restore, "function");
  assert.deepEqual(Array.from(controller.stored()), []);
});

test("pane presentation formats images and capacity through one component", () => {
  const view = paneView.create({
    esc: value => String(value),
    humanSize: value => `${value} B`,
  });
  assert.equal(view.paneFormat({ kind: "gemdos", name: "demo.st" }), "ST");
  assert.equal(view.paneFormat({ kind: "gemdos", name: "demo.msa" }), "MSA");
  assert.equal(view.paneFormat({ kind: "gemdos", name: "demo.dim" }), "DIM");
  assert.equal(view.paneFormat({ kind: "gemdos", containerFormat: "stx", name: "demo.stx" }), "STX");
  assert.equal(view.paneFormat({ kind: "gemdos", containerFormat: "hfe", name: "demo.hfe" }), "HFE");
  assert.equal(view.paneFormat({ kind: "gemdos", containerFormat: "scp", name: "demo.scp" }), "SCP");
  assert.equal(view.paneFormat({ kind: "gemdos", containerFormat: "ipf", name: "demo.ipf" }), "IPF");
  assert.equal(view.paneFormat({ kind: "hd", name: "scsi0.img" }), "HD");
  assert.equal(view.paneFormat({ kind: "vol", name: "c.img" }), "VOL");
  assert.equal(view.paneFormat({ kind: "iso", name: "disc.iso" }), "CD");
  assert.equal(view.paneFormat({ kind: "rom", name: "bank.rom" }), "ROM");
  assert.equal(view.paneFormat({ kind: "rom", name: "tos206.tos" }), "TOS");
  assert.match(view.capacityMarkup({ available: true, total: 100, used: 75, free: 25, unit: "bytes" }), /capacity warning/);
  // GEMDOS separates path components with a backslash and the root is the
  // drive letter. A full stop is an ordinary character in an 8.3 name, so a
  // folder named "OS-V3.5" is one crumb rather than two.
  assert.match(view.crumbs(""), /class="crumb current" data-path="">\\</);
  assert.match(view.crumbs("", false, "C"), /class="crumb current" data-path="">C:\\</);
  assert.match(view.crumbs("GAMES\\DEMOS"), /data-path="GAMES"/);
  assert.match(view.crumbs("GAMES\\DEMOS"), /data-path="GAMES\\DEMOS"/);
  assert.match(view.crumbs("GAMES/DEMOS"), /data-path="GAMES\\DEMOS"/);
  assert.equal((view.crumbs("OS-V3.5").match(/<button/g) || []).length, 2);
  assert.match(view.crumbs("OS-V3.5"), /data-path="OS-V3.5"/);
});

test("the pane export control follows the formats the service offers", () => {
  const view = paneView.create({ esc: value => String(value), humanSize: value => `${value} B` });

  const exportable = view.exportAvailability({
    name: "demo.st",
    exportFormats: [
      { format: "native", extension: "st", label: "Native sector image (.st)" },
      { format: "msa", extension: "msa", label: "Magic Shadow Archiver (.msa)" },
      { format: "hfe", extension: "hfe", label: "HxC HFE flux image (.hfe)" },
    ],
  });
  assert.equal(exportable.available, true);
  assert.match(exportable.label, /demo\.st/);

  // Anything with no compatible target says so rather than going missing.
  const unsupported = view.exportAvailability({ name: "bank.rom", exportFormats: [] });
  assert.equal(unsupported.available, false);
  assert.match(unsupported.label, /no compatible format/);

  // A missing field must read as unavailable, never as an enabled control.
  assert.equal(view.exportAvailability({ name: "old.st" }).available, false);
});

test("the pane export icon matches the other header controls", () => {
  const icons = visuals.PANE_ICONS;
  assert.ok(icons.exportImage, "the export control needs an icon");
  for (const [name, markup] of Object.entries(icons)) {
    assert.match(markup, /^<svg viewBox="0 0 24 24" aria-hidden="true">/, `${name} shares the icon frame`);
    assert.match(markup, /<\/svg>$/, `${name} is a complete element`);
  }
});

test("folder transfer planning preserves GEMDOS trees and resolves collisions", () => {
  const planning = transferPlanning.create({
    targetNameRule: (_pane, name) => ({ suggested: name.slice(0, 10), limit: 10 }),
  });
  const result = planning.folderTargetPlans(
    { image: { kind: "gemdos" } },
    [{ relativePath: "Pack/LongFilename" }, { relativePath: "Pack/LongFilename2" }],
    "preserve",
  );
  assert.deepEqual(Array.from(result.plans, item => item.targetPath), ["Pack\\LongFilena", "Pack\\LongFilen1"]);
  // A ROM bank has no folders, so only the leaf names survive.
  const flat = planning.folderTargetPlans({ image: { kind: "rom" } }, [{ relativePath: "Pack/LongFilename" }], "preserve");
  assert.deepEqual(Array.from(flat.plans, item => item.targetPath), ["LongFilena"]);
});
