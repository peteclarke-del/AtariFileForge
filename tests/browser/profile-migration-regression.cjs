// Stored hardware profiles move to each new schema without losing anything.
//
// Schema 8 added five presets. A list saved under an earlier schema holds the
// older presets and whatever its owner saved or edited, so it gains only the
// new presets it does not already hold by name, appended after everything
// else, so the active profile's index still points at the same profile.
const { chromium } = require("playwright");

const target = process.env.ATARI_FILE_FORGE_URL || "http://127.0.0.1:8666";
const KEY = "atari-file-forge-hardware-profiles";
const NEW = [
  "1040 STF · 1 MiB, ACSI2STM and a Gotek",
  "1040 STE · 4 MiB and ACSI2STM",
  "Mega ST · 4 MiB, blitter and BlueSCSI",
  "1040 STFM · 1 MiB and ACSI2STM",
  "520 STFM · 1 MiB and ACSI2STM",
];

async function migrate(page, profiles, schema) {
  // Opening the Workbench is what reads, and therefore migrates, the list.
  return page.evaluate(async ({ KEY, profiles, schema }) => {
    localStorage.clear();
    if (profiles) localStorage.setItem(KEY, JSON.stringify(profiles));
    if (schema) localStorage.setItem(`${KEY}-schema`, schema);
    localStorage.setItem("atari-file-forge-active-hardware-profile", "1");
    document.querySelector("#workbenchButton").click();
    // A closed dialog keeps its last content, so wait for it to be open again.
    const ready = () => document.querySelector("#modal").open && document.querySelector('[name="profileSelect"]');
    for (let tries = 0; tries < 50 && !ready(); tries += 1) {
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    const shown = [...document.querySelectorAll('[name="profileSelect"] option')].map(option => option.textContent);
    document.querySelector("#modal").close();
    return {
      stored: JSON.parse(localStorage.getItem(KEY)),
      schema: localStorage.getItem(`${KEY}-schema`),
      active: document.querySelector('[name="profileSelect"]')?.value ?? null,
      shown,
    };
  }, { KEY, profiles, schema });
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.goto(target, { waitUntil: "networkidle" });
    const fresh = await migrate(page, null, null);
    if (fresh.schema !== "8" || fresh.stored.length !== 17) {
      throw new Error(`A new install did not get the seventeen presets: ${fresh.schema} ${fresh.stored.length}`);
    }
    const older = fresh.stored.filter(profile => !NEW.includes(profile.name));
    const own = { name: "My own ST", machine: "st", addons: ["tos-104", "ram-1m"], filingSystem: "fat12", targetHardware: "floppy", driverBuild: "none" };
    const edited = { ...older[1], addons: [...older[1].addons, "printer"].filter((id, index, all) => all.indexOf(id) === index) };

    // Schema 7: the twelve older presets, one edited, and one of the owner's.
    const seven = await migrate(page, [older[0], edited, ...older.slice(2), own], "7");
    const names = seven.stored.map(profile => profile.name);
    if (seven.schema !== "8") throw new Error(`Schema 7 was not moved on: ${seven.schema}`);
    if (JSON.stringify(names) !== JSON.stringify([...older.map(profile => profile.name), "My own ST", ...NEW])) {
      throw new Error(`Schema 7 did not gain exactly the new presets at the end: ${JSON.stringify(names)}`);
    }
    if (JSON.stringify(seven.stored[1].addons) !== JSON.stringify(edited.addons)) {
      throw new Error("An edited preset was overwritten");
    }
    if (seven.shown[1] !== older[1].name) throw new Error("The active profile's index no longer names the same profile");

    // Someone who already saved a profile under one of the new names keeps theirs.
    const theirs = { ...own, name: NEW[2] };
    const clash = await migrate(page, [...older, theirs], "7");
    const copies = clash.stored.filter(profile => profile.name === NEW[2]);
    if (copies.length !== 1 || copies[0].machine !== "st") {
      throw new Error(`A saved profile with a new preset's name was duplicated or replaced: ${JSON.stringify(copies)}`);
    }
    if (clash.stored.length !== 17) throw new Error(`Expected 17 profiles, found ${clash.stored.length}`);

    // Schema 8 is left exactly as it was.
    const eight = await migrate(page, [own], "8");
    if (eight.stored.length !== 1) throw new Error("A schema 8 list was changed");

    console.log("Profile migration browser regression passed");
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
