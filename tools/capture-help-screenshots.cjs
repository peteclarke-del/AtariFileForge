// Regenerate the handbook screenshots from a running build.
//
// The images under app/static/help are checked in, because the handbook is
// served by the application itself and cannot go and take its own pictures.
// That makes them the part of the documentation most likely to fall behind the
// interface, so the way they were produced lives here rather than in somebody's
// shell history.
//
// The images are 2800x1760, which is a 1400x880 window at two device pixels per
// CSS pixel. Anything captured at another size looks wrong beside them, so the
// size lives in one place below.
//
//   ATARI_FILE_FORGE_URL=http://127.0.0.1:8666 \
//     node tools/capture-help-screenshots.cjs [name ...]
//
// Naming one or more shots takes only those, which is what you want when a
// single dialog has changed. With no names it takes everything it can.
//
// The application has to be running and it has to be able to reach the sample
// media in samples/. Every shot opens a real Atari disk and drives the real
// interface; nothing here is staged with fixtures, because a screenshot of a
// fixture teaches the reader about the fixture.
//
// A shot whose workflow this build does not offer is skipped with a message
// rather than failing, so the rest are still taken.

const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const VIEWPORT = { width: 1400, height: 880 };
const SCALE = 2;
const HELP = path.join(ROOT, "app", "static", "help");
const DOCS = path.join(ROOT, "docs", "images");
const SAMPLES = path.join(ROOT, "samples");
const target = process.env.ATARI_FILE_FORGE_URL || "http://127.0.0.1:8666";

// Three real Atari game disks and the operator's own drive images. Using real
// media is the point: a made-up disk with three files called TEST would show
// the reader nothing about what their own collection looks like in here.
const DISKS = {
  battleHawks: path.join(SAMPLES, "floppies", "Battle_Hawks_1942_1988_LucasFilm_Games_Protection_Removed.st"),
  // Red Heat has no GEMDOS filing system at all: it boots its own loader,
  // which is how a great many ST games were published. It is here because the
  // pictures that explain that case need a disk that really is like that.
  redHeat: path.join(SAMPLES, "floppies", "Red_Heat_1989_Ocean_cr_TDA.st"),
  rogueTrooper: path.join(SAMPLES, "floppies", "Rogue_Trooper_1990_Krisalis_Software_cr_Empire.st"),
};
const ROM = path.join(ROOT, "firmware", "emutos", "etos512uk.img");
// The operator's own ICD drive, because the drive pictures are about reading a
// drive that was prepared elsewhere. A drive this application made itself
// would show none of what those dialogs are for.
const DRIVE = path.join(SAMPLES, "hdd", "petari_acsi_800mb_icd.hd");
// A real tokenised GFA BASIC program. None of the sample game disks carries
// one, and a picture of the BASIC editor has to have BASIC in it.
const GFA_PROGRAM = path.join(ROOT, "tests", "fixtures", "basic", "tilemap.gfa");
// A folder of real host files whose names have to be changed to reach a
// GEMDOS volume: lower case throughout, and one name too long for eight
// characters. That is what the copy review is for.
const HOST_FOLDER = path.join(ROOT, "tests", "fixtures", "basic");

const wait = (page, ms) => page.waitForTimeout(ms);

// Menu items live inside a <details> popup that closes the moment focus moves,
// so Playwright's own click can find the element detached between deciding it
// is actionable and pressing it. Dispatching the click from inside the page
// avoids the race entirely.
async function click(page, selector) {
  const found = await page.evaluate(name => {
    const node = document.querySelector(name);
    if (!node) return false;
    node.click();
    return true;
  }, selector);
  if (!found) throw new Error(`No such control: ${selector}`);
  await wait(page, 1200);
}

// Whether this build offers a control at all. A workflow behind a flag should
// skip with a message rather than time out waiting for a dialog that is never
// going to open.
async function offers(page, selector) {
  return page.evaluate(name => {
    const node = document.querySelector(name);
    return Boolean(node) && !node.disabled && !node.hidden;
  }, selector);
}

async function paneMenu(page, label, paneIndex = 0) {
  await page
    .locator(".pane").nth(paneIndex)
    .locator(".tool-menu > summary").filter({ hasText: label }).first()
    .click();
  await wait(page, 400);
}

async function command(page, menu, cssClass, paneIndex = 0) {
  await paneMenu(page, menu, paneIndex);
  await click(page, `.pane[data-pane="${paneIndex}"] .${cssClass}`);
}

async function modalIsOpen(page) {
  return page.evaluate(() => Boolean(document.querySelector("#modal")?.open));
}

async function closeModal(page) {
  await page.evaluate(() => document.querySelector("#modal")?.close());
  await wait(page, 500);
}

async function openImage(page, file, paneIndex = 0, { asRawRom = false } = {}) {
  await page.locator(".pane").nth(paneIndex).locator(".pane-open").click();
  await wait(page, 1000);
  await page.setInputFiles('#modal input[name="images"]', [file]);
  await wait(page, 700);
  // A TOS ROM normally opens as its decoded segments, which is the right
  // default. The ROM Workbench works on the bytes, so those pictures ask for
  // the raw view the open dialog offers.
  if (asRawRom) {
    await page.evaluate(() => {
      const select = document.querySelector('#modal select[name="formatOverride"]');
      if (select) { select.value = "rom"; select.dispatchEvent(new Event("change", { bubbles: true })); }
    });
    await wait(page, 400);
  }
  await page.click("[data-open-selection]");
  // Opening reads and identifies the whole image, which on a hard disk takes a
  // while. Wait for the dialog to go rather than for a fixed time.
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await wait(page, 500);
    if (!(await modalIsOpen(page))) break;
  }
  // The dialog closes when the upload starts, not when it finishes. An 800 MB
  // drive keeps going for a minute or more after that, and a picture taken in
  // the meantime is a picture of a progress bar.
  for (let attempt = 0; attempt < 600; attempt += 1) {
    await wait(page, 1000);
    const ready = await page.evaluate(index => {
      const pane = document.querySelectorAll(".pane")[index];
      if (!pane || pane.querySelector(".empty-pane")) return false;
      return !/Uploading|Reading|Identifying/i.test(pane.textContent);
    }, paneIndex);
    if (ready) return;
  }
  throw new Error(`Pane ${paneIndex} never finished opening ${path.basename(file)}`);
}

// A hard disk opens on its partition table, and none of the file or install
// commands apply until one of its partitions is entered. Everything the drive
// pictures are about lives inside a partition, so this is where they start.
async function openDrive(page, file = DRIVE) {
  await openImage(page, file);
  await page.evaluate(() => {
    const row = document.querySelector(".pane .file-row[data-type=\"partition\"]");
    row?.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
  });
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await wait(page, 500);
    const inside = await page.evaluate(() =>
      !document.querySelector(".pane .file-row[data-type=\"partition\"]"));
    if (inside) break;
  }
  await wait(page, 2000);
}

// Toasts stack in the bottom corner and outlive the action that raised them.
// They are part of using the application and no part of a picture of a dialog,
// so they are cleared just before the shutter.
async function clearToasts(page) {
  await page.evaluate(() => {
    document.querySelectorAll(".toast-region > *").forEach(node => node.remove());
  });
  await wait(page, 250);
}

// Double-clicking a row is how anybody opens a file, and the editor picks its
// own view from what the bytes turn out to be.
async function openFile(page, name) {
  await page.evaluate(target => {
    const row = [...document.querySelectorAll(".pane .file-row")]
      .find(candidate => (candidate.dataset.name || "") === target);
    if (!row) throw new Error(`No such file on this disk: ${target}`);
    row.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
  }, name);
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await wait(page, 500);
    if (await modalIsOpen(page)) break;
  }
  await wait(page, 3000);
}

// Make a blank floppy in a pane, which is what the "New image" dialog does.
async function newFloppy(page, format, title, paneIndex = 0) {
  await page.locator(".pane").nth(paneIndex).locator(".pane-new").click();
  await wait(page, 1200);
  await page.evaluate(chosen => {
    const modal = document.querySelector("#modal");
    const select = modal.querySelector('select[name="format"]');
    select.value = chosen;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }, format);
  await wait(page, 500);
  await page.fill('#modal input[name="title"]', title);
  await click(page, '#modal button[value="create"]');
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await wait(page, 500);
    if (!(await modalIsOpen(page))) break;
  }
  await wait(page, 2500);
}

// Put a host file onto the open image and take whatever the plan dialog offers.
async function insertHostFile(page, file) {
  await paneMenu(page, "File");
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser", { timeout: 20000 }),
    page.evaluate(() => document.querySelector(".pane .import-file")?.click()),
  ]);
  await chooser.setFiles([file]);
  await wait(page, 3000);
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (!(await modalIsOpen(page))) break;
    const advanced = await page.evaluate(() => {
      const button = document.querySelector('#modal button[value="continue"], #modal button.primary:not([disabled])');
      if (!button) return false;
      button.click();
      return true;
    });
    if (!advanced) break;
    await wait(page, 2000);
  }
  await wait(page, 2500);
}

async function shot(page, directory, name) {
  await clearToasts(page);
  fs.mkdirSync(directory, { recursive: true });
  await page.screenshot({ path: path.join(directory, `${name}.png`) });
  console.log(`wrote ${path.relative(ROOT, path.join(directory, `${name}.png`))}`);
}

// Each entry takes one picture. `needs` names what has to be open first, so a
// single run can share one browser and one opened disk between related shots.
const SHOTS = [];
function scene(name, where, run) {
  SHOTS.push({ name, where, run });
}

scene("workspace", HELP, async page => {
  await openImage(page, DISKS.battleHawks, 0);
  await click(page, "#addPaneButton");
  await wait(page, 900);
  // A real game floppy beside the operator's own hard drive, because the two
  // kinds of medium behave differently and the workspace is where you see both
  // at once. Rogue Trooper and Red Heat both boot their own loaders and list
  // nothing, so neither makes a second pane worth looking at.
  await openImage(page, DRIVE, 1);
  // The two windows open on top of each other, and the picture is about there
  // being several of them, so move the second clear of the first.
  await page.evaluate(() => {
    const pane = document.querySelectorAll(".pane")[1];
    if (pane) { pane.style.left = "300px"; pane.style.top = "230px"; }
  });
  await wait(page, 1500);
});

scene("hex-editor", HELP, async page => {
  await openImage(page, DISKS.battleHawks);
  await command(page, "Tools", "open-hex-editor");
  await wait(page, 2500);
});

scene("health-dashboard", HELP, async page => {
  await openImage(page, DISKS.battleHawks);
  await command(page, "Analyse", "health-dashboard");
  await wait(page, 3000);
  // The reader is being shown what a failed record looks like, so open one.
  await page.evaluate(() => {
    const failed = [...document.querySelectorAll("#modal details")]
      .find(node => /fail|error|warning/i.test(node.textContent));
    if (failed) failed.open = true;
  });
  await wait(page, 900);
});

scene("duplicate-check", HELP, async page => {
  await openImage(page, DISKS.battleHawks);
  await command(page, "Analyse", "find-duplicates");
  await wait(page, 4000);
});

scene("online-library", HELP, async page => {
  await openImage(page, DISKS.battleHawks);
  await command(page, "Library", "online-library");
  await wait(page, 4000);
});

scene("private-collection", HELP, async page => {
  await openImage(page, DISKS.battleHawks);
  await command(page, "Library", "collection-catalogue");
  await wait(page, 4000);
});

scene("hardware-deployment-assistant", HELP, async page => {
  await openImage(page, DISKS.battleHawks);
  await command(page, "Tools", "build-deployment");
  await wait(page, 4000);
});

scene("hfe-create", HELP, async page => {
  await openImage(page, DISKS.battleHawks);
  await command(page, "File", "menu-new-matching-image");
  await wait(page, 1500);
  // The picture is about the HFE wrapper offered around each geometry, so the
  // list has to be showing one.
  await page.evaluate(() => {
    const select = document.querySelector('#modal select[name="format"]');
    if (select) {
      const hfe = [...select.options].find(option => /hfe/i.test(option.value));
      if (hfe) { select.value = hfe.value; select.dispatchEvent(new Event("change", { bubbles: true })); }
    }
  });
  await wait(page, 1200);
});

scene("rom-pane", HELP, async page => {
  await openImage(page, ROM);
  await wait(page, 2000);
});

scene("workbench-analysis", HELP, async page => {
  await openImage(page, DISKS.battleHawks);
  await paneMenu(page, "Analyse");
  await wait(page, 500);
});

// Insert a floppy into a drive and stop on the dialog that asks what to do
// with it. Both the import picture and the staging flow start here.
async function importDiskIntoDrive(page, disk) {
  await paneMenu(page, "File");
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser", { timeout: 20000 }),
    page.evaluate(() => document.querySelector(".pane .import-file")?.click()),
  ]);
  await chooser.setFiles([disk]);
  for (let attempt = 0; attempt < 40; attempt += 1) {
    await wait(page, 500);
    if (await page.evaluate(() => Boolean(document.querySelector('#modal select[name="storageMethod"]')))) return;
  }
  throw new Error("The import dialog never offered a storage method");
}

scene("image-import-preview", HELP, async page => {
  await openDrive(page);
  await importDiskIntoDrive(page, DISKS.battleHawks);
  await wait(page, 1500);
});

scene("drive-install", HELP, async page => {
  await openDrive(page);
  await command(page, "Tools", "prepare-drive");
  await wait(page, 3000);
});

scene("staged-installations", HELP, async page => {
  await openDrive(page);
  // A picture of an empty list teaches nobody what the list is for, so stage a
  // real disk onto the drive first and then go and look at it.
  await importDiskIntoDrive(page, DISKS.battleHawks);
  await page.evaluate(() => {
    const modal = document.querySelector("#modal");
    const method = modal.querySelector('select[name="storageMethod"]');
    method.value = "install";
    method.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await wait(page, 900);
  await page.evaluate(() => {
    const modal = document.querySelector("#modal");
    const stage = modal.querySelector('input[name="installMode"][value="stage"]');
    if (stage) { stage.checked = true; stage.dispatchEvent(new Event("change", { bubbles: true })); }
    const title = modal.querySelector('input[name="installTitle"]');
    if (title) { title.value = "Battle Hawks 1942"; title.dispatchEvent(new Event("input", { bubbles: true })); }
    const label = modal.querySelector('input[name="diskLabel"]');
    if (label) { label.value = "Disk 1"; label.dispatchEvent(new Event("input", { bubbles: true })); }
    const now = modal.querySelector('input[name="installNow"]');
    if (now) { now.checked = false; now.dispatchEvent(new Event("change", { bubbles: true })); }
  });
  await wait(page, 700);
  await click(page, '#modal button[value="continue"]');
  for (let attempt = 0; attempt < 90; attempt += 1) {
    await wait(page, 1000);
    if (!(await modalIsOpen(page))) break;
  }
  await wait(page, 2000);
  await command(page, "Tools", "staged-installations");
  await wait(page, 3500);
});

// The workbench opens on its Overview tab; the others are one click away.
async function romWorkbench(page, tab) {
  await openImage(page, ROM, 0, { asRawRom: true });
  await command(page, "Tools", "rom-workbench");
  await wait(page, 6000);
  if (tab) {
    await page.evaluate(name => {
      const button = [...document.querySelectorAll("#modal button")]
        .find(candidate => candidate.textContent.trim() === name);
      if (!button) throw new Error(`The ROM Workbench has no ${name} tab`);
      button.click();
    }, tab);
    await wait(page, 5000);
  }
}

scene("rom-workbench-overview", HELP, async page => {
  await romWorkbench(page, null);
});

scene("rom-decoder", HELP, async page => {
  // The decoded view is per bank, and it is reached by opening a bank the way
  // any other row is opened.
  await openImage(page, ROM, 0, { asRawRom: true });
  await click(page, ".pane .file-row .row-rom-inspect");
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await wait(page, 500);
    if (await modalIsOpen(page)) break;
  }
  await wait(page, 4000);
});

scene("rom-command-help", HELP, async page => {
  await openImage(page, ROM, 0, { asRawRom: true });
  await click(page, ".pane .file-row .row-rom-inspect");
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await wait(page, 500);
    if (await modalIsOpen(page)) break;
  }
  await wait(page, 3000);
  // Selecting the question mark pins the explanation open, which is the
  // behaviour the picture is there to show.
  await click(page, "#modal .rom-command-help");
  await wait(page, 1500);
  // Bring the pinned tooltip into view, since the table is below the fold.
  await page.evaluate(() => {
    document.querySelector("#modal .rom-command-help")
      ?.scrollIntoView({ block: "center" });
  });
  await wait(page, 1200);
});

scene("rom-workbench-disassembly", HELP, async page => {
  await romWorkbench(page, "Disassembly");
  // Disassemble the first bank so the picture shows annotated code rather
  // than an empty pane waiting for a button.
  await page.evaluate(() => {
    const button = [...document.querySelectorAll("#modal button")]
      .find(candidate => /disassemble/i.test(candidate.textContent));
    button?.click();
  });
  await wait(page, 8000);
});

scene("rom-workbench-programmer", HELP, async page => {
  await romWorkbench(page, "Programmer");
});

scene("file-editor-script", HELP, async page => {
  await openImage(page, DISKS.battleHawks);
  await openFile(page, "DESKTOP.INF");
});

scene("file-editor-disassembly", HELP, async page => {
  await openImage(page, DISKS.battleHawks);
  await openFile(page, "B_HAWK.PRG");
});

scene("file-editor-basic", HELP, async page => {
  await newFloppy(page, "ds-720k", "BASIC");
  await insertHostFile(page, GFA_PROGRAM);
  await openFile(page, "TILEMAP.GFA");
});

// Insert a host folder into the open volume and stop on the review that comes
// before anything is written.
async function importHostFolder(page, folder) {
  await paneMenu(page, "File");
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser", { timeout: 20000 }),
    page.evaluate(() => document.querySelector(".pane .import-folder")?.click()),
  ]);
  await chooser.setFiles([folder]);
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await wait(page, 500);
    if (await modalIsOpen(page)) break;
  }
  await wait(page, 4000);
}

scene("copy-name-preflight", HELP, async page => {
  await openDrive(page);
  await importHostFolder(page, HOST_FOLDER);
});

scene("destination-conflict", HELP, async page => {
  await openDrive(page);
  await importHostFolder(page, HOST_FOLDER);
  // Past the review is the dialog that decides where the files land and
  // whether an existing file of the same name is replaced.
  await click(page, '#modal button[value="continue"], #modal button.primary:not([disabled])');
  await wait(page, 4000);
});

module.exports = { SHOTS };

async function main() {
  const wanted = process.argv.slice(2);
  const chosen = wanted.length ? SHOTS.filter(entry => wanted.includes(entry.name)) : SHOTS;
  if (!chosen.length) {
    console.error(`No such shot. Known: ${SHOTS.map(entry => entry.name).join(", ")}`);
    process.exit(2);
  }
  for (const file of [...Object.values(DISKS), ROM, DRIVE]) {
    if (!fs.existsSync(file)) throw new Error(`Missing sample media: ${file}`);
  }
  let failures = 0;
  for (const entry of chosen) {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: SCALE });
    page.on("pageerror", error => console.error(`  page error: ${error.message}`));
    try {
      await page.goto(target, { waitUntil: "domcontentloaded" });
      await wait(page, 2000);
      await entry.run(page);
      await shot(page, entry.where, entry.name);
    } catch (error) {
      failures += 1;
      console.error(`skipped ${entry.name}.png: ${error.message.split("\n")[0]}`);
    } finally {
      await browser.close();
    }
  }
  if (failures) {
    console.error(`${failures} of ${chosen.length} shots were not taken.`);
    process.exit(1);
  }
}

if (require.main === module) {
  main().catch(error => { console.error(error); process.exit(1); });
}
