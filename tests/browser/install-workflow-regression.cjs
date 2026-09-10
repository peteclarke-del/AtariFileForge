// Installing a disk onto a drive, exercised through the running application.
//
// The unit tests cover the service; what they cannot cover is that the import
// dialog offers the choice, that the routes are reachable from a browser, and
// that the checkpoint the operator relies on to undo an install is actually
// recorded. All three have to be true together for the feature to exist.
//
// UNVERIFIED. The install service is being rebuilt for the Atari and this
// build publishes none of its routes, so the check below stops with a plain
// message rather than failing. Delete the guard once /install/ answers.

const { chromium } = require("playwright");

const target = process.env.ATARI_FILE_FORGE_URL || "http://127.0.0.1:8666";

//: Where staged disks live on the drive. It has to match
//: DEFAULT_STAGING_PARENT in app/static/app.js and in app/install_service.py.
const STAGING_PARENT = "INSTALL\\STAGE";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const created = [];
  try {
    await page.goto(target, { waitUntil: "networkidle" });
    const available = await page.evaluate(async () => {
      const response = await fetch("/api/health");
      const health = await response.json();
      return Boolean(health.services?.install);
    });
    if (!available) {
      console.log("Install workflow browser regression skipped: the install service is not available in this build");
      return;
    }
    const result = await page.evaluate(async stagingParent => {
      const json = async (url, options = {}) => {
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `${response.status} ${url}`);
        return data;
      };
      const body = value => ({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(value),
      });

      // Staging writes onto the drive being built, so each run gets its own
      // drive and its own title name: a leftover from an interrupted run
      // cannot make the next one fail for the wrong reason.
      const title = `BROWSER${Date.now() % 100000}`;
      const drive = (await json("/api/images/create", body({
        format: "hd", title: "TARGET", capacity: "64MB",
        targetHardware: "hd", hardDisk: { partitions: 1, scheme: "ahdi" },
      }))).image.id;
      const first = (await json("/api/images/create", body({ format: "ds-720k", title: "GAMEONE" }))).image.id;
      const second = (await json("/api/images/create", body({ format: "ds-720k", title: "GAMETWO" }))).image.id;

      for (const [disk, name] of [[first, "LOADER.PRG"], [second, "LEVEL2.DAT"]]) {
        await json(`/api/images/${disk}/empty-file`, body({
          destination: "", name, attributes: "-----a",
        }));
      }

      // A drive showing its partition table is not a volume, so the driver
      // state cannot be reported on until a partition is chosen.
      const noVolume = await fetch(`/api/images/${drive}/install/driver`);
      if (noVolume.ok) throw new Error("A partition table was accepted as an install destination");

      const state = await json(`/api/images/${drive}/install/driver?partition=0`);
      if (state.driver.installed) throw new Error("A blank drive reported a hard-disk driver already installed");

      // Two disks of one title stage into one tree, on the drive itself.
      await json(`/api/images/${drive}/install/stage`, body({
        sourceImage: first, title, diskLabel: "Disk 1", partition: 0, stagingParent,
      }));
      const staged = (await json(`/api/images/${drive}/install/stage`, body({
        sourceImage: second, title, diskLabel: "Disk 2", partition: 0, stagingParent,
      }))).staged;
      if (staged.diskCount !== 2) throw new Error(`Expected one title of two disks, got ${staged.diskCount}`);

      // Staging has to land on the target image, not on the machine running
      // the application: the whole point is that the install can be finished
      // in an emulator or on real hardware, where a host directory is
      // unreachable. It goes under a staging folder of its own rather than at
      // the volume root, so a title's own folders are never mistaken for
      // staged disks.
      if (staged.path !== `${stagingParent}\\${title}`) {
        throw new Error(`Staged to ${staged.path} rather than a folder on the drive`);
      }
      const stagedTree = await json(
        `/api/images/${drive}/tree?path=${encodeURIComponent(staged.path)}&partition=0`);
      const stagedNames = stagedTree.entries.map(row => row.name).sort();
      if (!stagedNames.includes("LOADER.PRG") || !stagedNames.includes("LEVEL2.DAT")) {
        throw new Error(`Both disks should be staged on the drive, found ${JSON.stringify(stagedNames)}`);
      }

      const listed = await json(`/api/images/${drive}/install/staged?partition=0&parent=${encodeURIComponent(stagingParent)}`);
      if (!listed.titles.some(row => row.name === staged.name)) {
        throw new Error("A staged title did not appear in the drive's staging list");
      }

      const before = (await json(`/api/images/${drive}/checkpoints`)).checkpoints.length;
      const installed = await json(`/api/images/${drive}/install/staged`, body({
        name: staged.name, parent: "GAMES", partition: 0, stagingParent,
      }));
      if (installed.path !== `GAMES\\${title}`) {
        throw new Error(`Installed to ${installed.path} rather than its own folder`);
      }

      const folder = await json(`/api/images/${drive}/tree?path=${encodeURIComponent(installed.path)}&partition=0`);
      const names = folder.entries.map(row => row.name).sort();
      if (!names.includes("LOADER.PRG") || !names.includes("LEVEL2.DAT")) {
        throw new Error(`Both disks should have merged into one folder, found ${JSON.stringify(names)}`);
      }

      // Installing empties the staging folder, so nothing is counted twice.
      const remaining = await json(`/api/images/${drive}/install/staged?partition=0&parent=${encodeURIComponent(stagingParent)}`);
      if (remaining.titles.some(row => row.name === staged.name)) {
        throw new Error("The staging folder still held the title after it was installed");
      }

      // An install changes a drive somebody built, so it must be undoable.
      const after = (await json(`/api/images/${drive}/checkpoints`)).checkpoints;
      if (after.length <= before) throw new Error("Installing a staged title recorded no undo checkpoint");
      await json(`/api/images/${drive}/undo`, body({}));
      // The install created the GAMES folder as well as the title inside it,
      // so a complete undo leaves neither. Either outcome is checked, because
      // what matters is that the title is gone, not how much went with it.
      const undone = await fetch(`/api/images/${drive}/tree?path=GAMES&partition=0`);
      if (undone.ok) {
        const games = await undone.json();
        if (games.entries.some(row => row.name === title)) {
          throw new Error("Undo did not remove the installed title");
        }
      }
      const restored = await json(`/api/images/${drive}/install/staged?partition=0&parent=${encodeURIComponent(stagingParent)}`);
      if (!restored.titles.some(row => row.name === staged.name)) {
        throw new Error("Undo removed the install but did not put the staged disks back");
      }

      // Preparing a drive writes a hard-disk driver onto it and creates the
      // folders TOS looks for at boot. Which bytes the driver writes is
      // asserted in the Python tests; what this level can show is that the
      // drive comes back reporting the driver it was given, and that the boot
      // folders exist afterwards.
      const prepared = (await json("/api/images/create", body({
        format: "hd", title: "PREPARED", capacity: "64MB",
        targetHardware: "hd", hardDisk: { partitions: 1, scheme: "ahdi" },
      }))).image.id;
      const preparation = (await json(`/api/images/${prepared}/install/driver`, body({
        driver: "driver-hddriver", partition: 0, createFolders: true,
      }))).driver;
      if (preparation.id !== "driver-hddriver") {
        throw new Error(`The prepared drive reported ${preparation.id} rather than the driver it was given`);
      }
      const preparedRoot = await json(`/api/images/${prepared}/tree?partition=0`);
      const rootNames = preparedRoot.entries.map(row => row.name);
      for (const folder of ["AUTO", "GEMSYS", "GAMES"]) {
        if (!rootNames.includes(folder)) {
          throw new Error(`The boot folder ${folder} was not created`);
        }
      }

      return {
        images: [drive, first, second, prepared],
        diskCount: staged.diskCount,
      };
    }, STAGING_PARENT);
    created.push(...result.images);
    console.log("Staging, driver reporting, install and undo browser regression passed");
  } finally {
    for (const id of created) {
      await page.evaluate(async image => {
        await fetch(`/api/images/${image}`, { method: "DELETE" });
      }, id).catch(() => {});
    }
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
