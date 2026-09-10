(() => {
  "use strict";

  // GEMDOS names are 8.3: up to eight characters, a full stop, up to three
  // more, stored in upper case. These characters can never appear in one.
  const GEMDOS_FORBIDDEN = '\\/:*?"<>|+,;=[] ';
  const NAME_LIMIT = 8;
  const EXTENSION_LIMIT = 3;

  const escapeForClass = text => text.replace(/[.*+?^${}()|[\]\\-]/g, "\\$&");

  // Splits a host name into the stem and extension GEMDOS would keep, and
  // replaces every character it cannot store. A name is upper-cased because
  // that is how TOS writes it, whatever the program asked for.
  function gemdosParts(original, forbidden = GEMDOS_FORBIDDEN) {
    const raw = String(original || "").split(/[/\\]/).pop();
    const invalid = new RegExp(`[${escapeForClass(forbidden)}\\x00-\\x1f\\x7f]`, "g");
    const clean = Array.from(raw.normalize("NFKC"), character => (character.codePointAt(0) > 0xFF ? "_" : character))
      .join("")
      .replace(invalid, "_")
      .toUpperCase();
    const dot = clean.lastIndexOf(".");
    const stem = (dot > 0 ? clean.slice(0, dot) : clean).replace(/\./g, "_");
    const extension = dot > 0 ? clean.slice(dot + 1).replace(/\./g, "_") : "";
    return { raw, stem, extension };
  }

  function joinParts(stem, extension) {
    return extension ? `${stem}.${extension}` : stem;
  }

  function targetNameRule(pane, original) {
    const policyKey = pane?.image?.kind === "hd" && pane?.partition == null ? "disk" : "file";
    const contract = pane?.image?.filenamePolicies?.[policyKey];
    if (pane?.image?.kind === "rom") return { valid: true, suggested: original, limit: Number(contract?.limit || 180), label: contract?.label || "ROM bank", adjusted: false, truncated: false };
    const forbidden = String(contract?.forbidden || GEMDOS_FORBIDDEN);
    const nameLimit = Number(contract?.nameLimit || NAME_LIMIT);
    const extensionLimit = Number(contract?.extensionLimit || EXTENSION_LIMIT);
    const limit = Number(contract?.limit || nameLimit + 1 + extensionLimit);
    const label = contract?.label || "GEMDOS 8.3";
    const { raw, stem, extension } = gemdosParts(original, forbidden);
    let suggested = joinParts(stem.slice(0, nameLimit), extension.slice(0, extensionLimit));
    if (!suggested || suggested === ".") suggested = "FILE";
    const rawParts = raw.split(".");
    const rawStem = rawParts.length > 1 ? rawParts.slice(0, -1).join(".") : raw;
    const rawExtension = rawParts.length > 1 ? rawParts.at(-1) : "";
    const valid = raw.length > 0
      && raw === raw.toUpperCase()
      && rawStem.length > 0
      && rawStem.length <= nameLimit
      && rawExtension.length <= extensionLimit
      && !rawStem.includes(".")
      && !new RegExp(`[${escapeForClass(forbidden)}\\x00-\\x1f\\x7f]`).test(raw)
      && Array.from(raw).every(character => character.codePointAt(0) <= 0xFF);
    const truncated = stem.length > nameLimit || extension.length > extensionLimit;
    return { valid, suggested, limit, label, adjusted: !valid || raw !== suggested, truncated };
  }

  function ignoredFolderFile(name) {
    const parts = String(name).replace(/\\/g, "/").split("/");
    const leaf = parts.at(-1).toLowerCase();
    return leaf === ".ds_store" || leaf === "thumbs.db" || leaf === "desktop.ini"
      || parts.some(part => part === "__MACOSX");
  }

  // The GEMDOS attribute byte, either as the six letters "rhsvda" with a dash
  // for each clear bit, or as the byte in hexadecimal, which an .inf sidecar
  // written by another tool sometimes uses.
  const ATTRIBUTE_LETTERS = "rhsvda";

  function normaliseAttributes(value) {
    const text = String(value || "").trim();
    const lowered = text.toLowerCase();
    if (
      lowered.length === ATTRIBUTE_LETTERS.length
      && [...lowered].every((character, index) => (
        character === "-" || character === ATTRIBUTE_LETTERS[index]
      ))
    ) return lowered;
    const hex = text.match(/^(?:0x|&h?|\$)([0-9a-f]{1,2})$/i);
    return hex ? `0x${hex[1].toUpperCase().padStart(2, "0")}` : "";
  }

  //: A TOS floppy has 512-byte sectors grouped in clusters of two, so a
  //: file costs 1 KiB for every started kilobyte. The boot sector, the two
  //: FAT copies and the root directory come off the top of each disk, and
  //: the root directory can hold only a fixed number of entries.
  const SECTOR_SIZE = 512;
  const SECTORS_PER_CLUSTER = 2;
  const DISK_FORMATS = Object.freeze({
    "720k": { sectors: 1440, fatSectors: 5, rootEntries: 112, label: "720 KiB double sided, 9 sectors per track" },
    "800k": { sectors: 1600, fatSectors: 5, rootEntries: 112, label: "800 KiB double sided, 10 sectors per track" },
    "880k": { sectors: 1760, fatSectors: 6, rootEntries: 112, label: "880 KiB double sided, 11 sectors per track" },
    "1440k": { sectors: 2880, fatSectors: 9, rootEntries: 224, label: "1.44 MiB high density, 18 sectors per track" },
  });

  function diskFormatSpec(diskFormat) {
    const key = String(diskFormat || "720k").toLowerCase().replace(/\s+/g, "").replace(/(kib|kb|k)$/, "k");
    const alias = { "720": "720k", "800": "800k", "880": "880k", "1440": "1440k", "1.44m": "1440k", "1.44mb": "1440k", st: "720k", msa: "720k", hd: "1440k" }[key] || key;
    return DISK_FORMATS[alias] || DISK_FORMATS["720k"];
  }

  function dataClusters(spec) {
    const rootSectors = Math.ceil(spec.rootEntries * 32 / SECTOR_SIZE);
    const reserved = 1 + 2 * spec.fatSectors + rootSectors;
    return Math.floor((spec.sectors - reserved) / SECTORS_PER_CLUSTER);
  }

  // A floppy is one volume, so a disk is filled and then a new one is
  // started. Files go into the root directory, so both the cluster count and
  // the entry count are limits.
  function allocateFilesToDisks(items, diskFormat) {
    const spec = diskFormatSpec(diskFormat);
    const capacity = dataClusters(spec);
    const clusterBytes = SECTOR_SIZE * SECTORS_PER_CLUSTER;
    const disks = [];
    let disk = null;
    let used = 0;
    for (const item of items) {
      const clusters = Math.ceil(Number(item.length || 0) / clusterBytes);
      if (clusters > capacity) throw new Error(`${item.name} is too large for one ${spec.label.split(",")[0]} disk.`);
      if (!disk || used + clusters > capacity || disk.files.length >= spec.rootEntries) {
        disk = { files: [], format: spec.label };
        disks.push(disk);
        used = 0;
      }
      disk.files.push({ ...item, targetSide: 0 });
      used += clusters;
    }
    return disks;
  }

  //: GEMDOS compares names without regard to case and stores them in upper
  //: case, so two files whose names differ only in case cannot share a
  //: folder, and a name cut to eight characters is made unique with a
  //: numeric suffix.
  function uniqueGemdosNames(items) {
    const used = new Set();
    return items.map(item => {
      const rule = targetNameRule({ image: { kind: "gemdos" } }, item.name);
      let proposed = rule.suggested;
      let suffix = 1;
      while (used.has(proposed.toUpperCase())) {
        const tail = String(suffix++);
        const dot = rule.suggested.lastIndexOf(".");
        const stem = dot > 0 ? rule.suggested.slice(0, dot) : rule.suggested;
        const extension = dot > 0 ? rule.suggested.slice(dot) : "";
        proposed = `${stem.slice(0, Math.max(1, NAME_LIMIT - tail.length))}${tail}${extension}`;
      }
      used.add(proposed.toUpperCase());
      // The source folder becomes the destination folder, so a copied tree
      // keeps the shape it had.
      const parts = String(item.path || "").replace(/\\/g, "/").split("/").slice(0, -1);
      return { ...item, targetName: proposed, prefix: parts.join("\\") };
    });
  }

  window.AtariImportPlanning = Object.freeze({
    DISK_FORMATS,
    GEMDOS_FORBIDDEN,
    allocateFilesToDisks,
    ignoredFolderFile,
    normaliseAttributes,
    targetNameRule,
    uniqueGemdosNames,
    // The names app.js still imports.
  });
})();
