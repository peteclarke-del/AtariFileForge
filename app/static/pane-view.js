window.AtariPaneView = (() => {
  function create({ esc, humanSize }) {
    // The badge on a pane header names the container the bytes arrived in,
    // or the kind of thing inside it when the container is not the point.
    const CONTAINER_BADGES = Object.freeze({
      st: "ST", msa: "MSA", dim: "DIM", stx: "STX", hfe: "HFE", scp: "SCP", ipf: "IPF",
      ahdi: "HD", hd: "HD", vol: "VOL", iso: "CD", cd: "CD", rom: "ROM", tos: "TOS",
    });
    const paneFormat = image => {
      const container = String(image.containerFormat || "").toLowerCase();
      if (CONTAINER_BADGES[container]) return CONTAINER_BADGES[container];
      const kind = String(image.kind || "").toLowerCase();
      if (kind === "hd" || kind === "ahdi") return "HD";
      if (kind === "vol" || kind === "partition") return "VOL";
      if (kind === "iso" || kind === "cd") return "CD";
      if (kind === "rom" || kind === "tos") return /\.tos$|^tos/i.test(String(image.name || "")) ? "TOS" : "ROM";
      const extension = String(image.name || "").toLowerCase().match(/\.([a-z0-9]+)$/)?.[1] || "";
      if (CONTAINER_BADGES[extension]) return CONTAINER_BADGES[extension];
      return "ST";
    };

    const capacityMarkup = capacity => {
      if (!capacity?.available || !capacity.total) {
        const reason = capacity?.reason || "Free-space information is loading.";
        return `<span class="capacity unavailable" title="${esc(reason)}" aria-label="${esc(reason)}"><i></i></span>`;
      }
      const usedPercent = Math.max(0, Math.min(100, capacity.used * 100 / capacity.total));
      const level = usedPercent >= 90 ? "critical" : usedPercent >= 70 ? "warning" : "healthy";
      const details = ["partitions", "banks"].includes(capacity.unit)
        ? `${capacity.free} free ${capacity.unit.slice(0, -1)}${capacity.free === 1 ? "" : "s"} of ${capacity.total} · ${capacity.used} in use · ${usedPercent.toFixed(1)}% full`
        : `${humanSize(capacity.free)} free of ${humanSize(capacity.total)} · ${humanSize(capacity.used)} used · ${usedPercent.toFixed(1)}% full`;
      return `<span class="capacity ${level}" role="progressbar" aria-label="${esc(details)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${usedPercent.toFixed(1)}" title="${esc(details)}" style="--capacity-used:${usedPercent}%"><i></i></span>`;
    };

    // GEMDOS separates path components with a backslash, and a drive letter
    // names the volume root, so the bar reads "C:\ › GAMES › ELITE". A full
    // stop is an ordinary character in an 8.3 name, so "OS-V3.5" is one
    // crumb. The flat form is kept for a pane that shows grouped results
    // rather than a folder tree.
    const crumbs = (path, flat = false, drive = "") => {
      if (flat) {
        if (path === "") return '<span class="crumb current">Catalogues</span>';
        return `<button class="crumb" data-path="">Catalogues</button><span>›</span><span class="crumb current">${esc(path)}</span>`;
      }
      const parts = String(path ?? "").replace(/^[A-Za-z]:/, "").replace(/^[$:]/, "").split(/[\\/]/).filter(Boolean);
      const letter = String(drive || "").trim().toUpperCase().replace(/:$/, "");
      const rootLabel = letter ? `${letter}:\\` : "\\";
      const root = `<button class="crumb${parts.length ? "" : " current"}" data-path="">${esc(rootLabel)}</button>`;
      return root + parts.map((part, index) => {
        const current = parts.slice(0, index + 1).join("\\");
        const klass = index === parts.length - 1 ? "crumb current" : "crumb";
        return `<span>›</span><button class="${klass}" data-path="${esc(current)}">${esc(part)}</button>`;
      }).join("");
    };

    const archiveCrumbs = pane => {
      const parts = String(pane.archiveMember || "").split(/[\\/]/).filter(Boolean);
      let member = "";
      const children = parts.map((part, index) => {
        member = member ? `${member}\\${part}` : part;
        const current = index === parts.length - 1;
        return `${current ? '<span class="crumb current">' : `<button class="crumb" data-archive-member="${esc(member)}">`}› ${esc(part)}${current ? "</span>" : "</button>"}`;
      }).join("");
      return `<button class="crumb archive-exit" title="Return to the containing filing system">${esc(pane.archiveName || "Archive")}</button>${children}`;
    };

    // Whether this image's sectors can be converted to another container, and
    // the wording for the header control either way. The button stays visible
    // when unavailable so the capability is discoverable, and says why.
    const exportAvailability = image => {
      const formats = image.exportFormats || [];
      if (formats.length) {
        return { available: true, label: `Export ${image.name} as another format` };
      }
      return { available: false, label: "Export as… · no compatible format for this media" };
    };

    return { archiveCrumbs, capacityMarkup, crumbs, exportAvailability, paneFormat };
  }

  return { create };
})();
