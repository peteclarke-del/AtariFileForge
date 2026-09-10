// Regenerate the handbook screenshots for the drive-preparation workflow.
//
// The images under app/static/help are checked in, because the handbook is
// served from the application itself and cannot go and take its own pictures.
// That makes them the part of the documentation most likely to fall behind the
// interface, so the way they were produced is kept here rather than in
// somebody's shell history.
//
// The existing images are 2800x1760, which is a 1400x880 window at two device
// pixels per CSS pixel. Anything captured at another size looks wrong beside
// them, so the size lives in one place below.
//
//   ATARI_INSTALL_DISKS=/path/to/st-images \
//     node tools/capture-help-screenshots.cjs
//
// The application has to be running; ATARI_FILE_FORGE_URL points at it and
// defaults to the port the container listens on. The staging shots need a
// folder of ST floppy images, which is what ATARI_INSTALL_DISKS names. Without
// it those shots are skipped rather than taken empty, because a picture of the
// dialog with nothing chosen teaches the reader nothing about the part that
// matters.
//
// Two of these shots depend on workflows that are being rebuilt. The script
// checks whether the application offers them and skips with a message rather
// than failing, so the shots it can take are still taken.

const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const VIEWPORT = { width: 1400, height: 880 };
const SCALE = 2;
const OUTPUT = path.join(__dirname, "..", "app", "static", "help");
const target = process.env.ATARI_FILE_FORGE_URL || "http://127.0.0.1:8666";
const disks = process.env.ATARI_INSTALL_DISKS || "";

const wait = (page, ms) => page.waitForTimeout(ms);

async function openPaneMenu(page, label) {
  await page.locator(".pane .tool-menu > summary", { hasText: label }).first().click();
  await wait(page, 250);
}

// A drive is not a volume. It opens on its partition table, and none of the
// file commands apply until one of its partitions is chosen.
async function newHardDrive(page, title) {
  await page.click(".empty-pane .pane-new");
  await wait(page, 800);
  await page.selectOption('#modal select[name="format"]', "hd");
  await page.fill('#modal input[name="title"]', title);
  await page.click('#modal button[value="create"]');
  await wait(page, 4000);
  await page.evaluate(() => {
    const row = [...document.querySelectorAll(".pane .file-row")].find(r => /\bC:/.test(r.textContent));
    row?.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
  });
  await wait(page, 1500);
}

function diskImages() {
  if (!disks) return [];
  const files = fs.readdirSync(disks)
    .filter(name => /\.(st|msa|dim|stx|hfe)$/i.test(name))
    .map(name => path.join(disks, name));
  if (!files.length) throw new Error(`No disk images in ${disks}`);
  return files;
}

// Whether the application offers a control at all. The install and audit
// workflows are behind a flag while their backend is rebuilt, and a screenshot
// run should say so rather than time out waiting for a dialog.
async function offers(page, selector) {
  return page.evaluate(name => {
    const node = document.querySelector(name);
    return Boolean(node) && !node.disabled && !node.hidden;
  }, selector);
}

async function capturePrepareDrive(page) {
  await newHardDrive(page, "SYSTEM");
  await openPaneMenu(page, "Tools");
  if (!(await offers(page, ".pane .prepare-drive"))) {
    console.log("skipped drive-install.png: this build does not offer Prepare drive yet");
    return false;
  }
  await page.click(".pane .prepare-drive");
  await wait(page, 1200);
  await page.screenshot({ path: path.join(OUTPUT, "drive-install.png") });
  console.log("wrote drive-install.png");
  await page.keyboard.press("Escape");
  await wait(page, 600);
  return true;
}

// Stage one disk so the staged list has something in it. A picture of an empty
// list would not show the reader what the dialog is for.
async function captureStagedInstallations(page, disk) {
  await openPaneMenu(page, "File");
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.click(".pane .import-file"),
  ]);
  await chooser.setFiles([disk]);
  await wait(page, 4000);
  if (await page.$('#modal button[name="action"][value="continue"]')) {
    await page.click('#modal button[name="action"][value="continue"]');
    await wait(page, 3500);
  }
  if (!(await page.$('#modal select[name="storageMethod"]'))) {
    console.log("skipped staged-installations.png: this build does not offer staging yet");
    return;
  }
  await page.selectOption('#modal select[name="storageMethod"]', "install");
  await wait(page, 700);
  await page.fill('#modal input[name="installTitle"]', "Hyper Sports");
  await page.fill('#modal input[name="diskLabel"]', "Disk 1");
  // Stage it without installing, which is what the staged list is about.
  await page.evaluate(() => {
    const now = document.querySelector('input[name="installNow"]');
    if (now) now.checked = false;
  });
  await page.click('#modal button.primary[value="continue"]');
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await wait(page, 800);
    if (!(await page.evaluate(() => document.querySelector("#modal").open))) break;
  }
  await wait(page, 1500);

  await openPaneMenu(page, "Tools");
  if (!(await offers(page, ".pane .staged-installations"))) {
    console.log("skipped staged-installations.png: this build does not offer the staged list yet");
    return;
  }
  await page.click(".pane .staged-installations");
  await wait(page, 2000);
  await page.screenshot({ path: path.join(OUTPUT, "staged-installations.png") });
  console.log("wrote staged-installations.png");
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: SCALE });
  page.on("pageerror", error => console.error("page error:", error.message));
  try {
    // The application polls while it is idle, so "networkidle" never arrives.
    await page.goto(target, { waitUntil: "domcontentloaded" });
    await wait(page, 1500);
    const prepared = await capturePrepareDrive(page);
    const files = diskImages();
    if (prepared && files.length) {
      await captureStagedInstallations(page, files[files.length - 1]);
    } else if (!files.length) {
      console.log("skipped staged-installations.png: set ATARI_INSTALL_DISKS to a folder of ST images");
    }
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
