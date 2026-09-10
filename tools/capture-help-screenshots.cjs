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
  redHeat: path.join(SAMPLES, "floppies", "Red_Heat_1989_Ocean_cr_TDA.st"),
  rogueTrooper: path.join(SAMPLES, "floppies", "Rogue_Trooper_1990_Krisalis_Software_cr_Empire.st"),
};
const ROM = path.join(ROOT, "firmware", "emutos", "etos512uk.img");

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

async function openImage(page, file, paneIndex = 0) {
  await page.locator(".pane").nth(paneIndex).locator(".pane-open").click();
  await wait(page, 1000);
  await page.setInputFiles('#modal input[name="images"]', [file]);
  await wait(page, 700);
  await page.click("[data-open-selection]");
  // Opening reads and identifies the whole image, which on a hard disk takes a
  // while. Wait for the dialog to go rather than for a fixed time.
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await wait(page, 500);
    if (!(await modalIsOpen(page))) break;
  }
  await wait(page, 2500);
}

async function shot(page, directory, name) {
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
  await click(page, ".topbar .add-pane, .topbar button[data-add-pane]").catch(() => {});
  await wait(page, 800);
  if (await page.locator(".pane").nth(1).locator(".pane-open").count()) {
    await openImage(page, DISKS.redHeat, 1);
  }
  await wait(page, 1200);
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

module.exports = { SHOTS };

async function main() {
  const wanted = process.argv.slice(2);
  const chosen = wanted.length ? SHOTS.filter(entry => wanted.includes(entry.name)) : SHOTS;
  if (!chosen.length) {
    console.error(`No such shot. Known: ${SHOTS.map(entry => entry.name).join(", ")}`);
    process.exit(2);
  }
  for (const file of [...Object.values(DISKS), ROM]) {
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
