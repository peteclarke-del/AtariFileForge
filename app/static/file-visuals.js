window.AtariFileVisuals = (() => {
  const PANE_ICONS = {
    newImage: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4V20.5H6z"/><path d="M14 3.5v4h4M9 14h6M12 11v6"/></svg>',
    loadImage: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 19.5V5.5h6l2 2h8v3"/><path d="M3.5 19.5 6 10.5h15l-2.5 9z"/></svg>',
    saveImage: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 3.5h13l3 3v14H4z"/><path d="M7 3.5v6h9v-6M7.5 20.5v-7h9v7"/></svg>',
    exportImage: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 14.5v6h15v-6"/><path d="M12 3.5v11M8 7.5l4-4 4 4"/></svg>',
    refreshView: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.5 8.5A8 8 0 1 0 20 15"/><path d="M19.5 3.5v5h-5"/></svg>',
    minimizePane: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 17.5h12"/></svg>',
    maximizePane: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5.5" y="5.5" width="13" height="13" rx="1"/></svg>',
    closePane: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6.5 6.5 11 11M17.5 6.5l-11 11"/></svg>',
  };

  const FILE_ICONS = {
    folder: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 6.5h6l2 2h9v10h-17z"/><path d="M3.5 9.5h17"/></svg>',
    folderUp: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 6.5h6l2 2h9v10h-17z"/><path d="M12 16v-5m-2 2 2-2 2 2"/></svg>',
    catalogue: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 6.5h6l2 2h9v10h-17z"/><path d="M7 12h2m2 0h2m2 0h2M7 15h2m2 0h2m2 0h2"/></svg>',
    disk: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3.5h12l2 2v15H5z"/><path d="M8 3.5v6h8v-6M8 20.5v-7h8v7"/></svg>',
    rom: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1"/><path d="M9 2.5v3m3-3v3m3-3v3M9 18.5v3m3-3v3m3-3v3M2.5 9h3m-3 3h3m-3 3h3m13-6h3m-3 3h3m-3 3h3"/></svg>',
    archive: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h12v17H6z"/><path d="M10 3.5v3h4v3h-4v3h4v3h-4v3h4"/></svg>',
    basic: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4"/><text x="12" y="16.5" text-anchor="middle">B</text></svg>',
    script: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4M9 12l2 2-2 2m3.5 0H16"/></svg>',
    text: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4M9 11h6m-6 3h6m-6 3h4"/></svg>',
    binary: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4"/><text x="12" y="16.5" text-anchor="middle">01</text></svg>',
    file: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4"/></svg>',
  };

  // The names GEMDOS gives its files are 8.3 and case-insensitive, so the
  // extension is the strongest hint a listing offers before the bytes are
  // read. Archives and disk images share one icon because both are containers
  // the pane can open in place.
  const executableNamePattern = /\.(?:prg|tos|ttp|app|acc|gtp)$/i;
  const basicNamePattern = /\.(?:gfa|bas|lst|sto|stb|mbs)$/i;
  const systemNamePattern = /\.(?:inf|cpx|rsc|sys|cnf|acx|prx|apx|xfs|xdd)$/i;
  const pictureNamePattern = /\.(?:img|pi1|pi2|pi3|pc1|pc2|pc3|neo|deg|degas|iff|tny|tn1|tn2|tn3|spu|spc|gif|xga|tga)$/i;
  const musicNamePattern = /\.(?:mod|snd|sndh|sam|avr|dvs|mus|ym|sc68|mid|midi)$/i;
  const archiveNamePattern = /\.(?:st|msa|dim|stx|zip|lzh|lha|arc|arj|zoo|tar|gz|tgz|hfe|scp|ipf)$/i;
  const textNamePattern = /\.(?:txt|doc|asc|readme|1st|me|nfo|diz|hyp|c|h|s|asm)$/i;
  // The desktop reads DESKTOP.INF (TOS 1), NEWDESK.INF (TOS 2 and 3) and
  // EMUDESK.INF (EmuTOS) at boot; MINT.CNF configures the kernel; the rest
  // are the conventional names for other configuration and driver files.
  const scriptNamePattern = /^(?:desktop\.inf|newdesk\.inf|emudesk\.inf|mint\.cnf|.+\.inf|.+\.cnf|.+\.sys)$/i;

  function fileKindKey(pane, name) {
    return [pane.partition ?? "image", pane.side ?? "side", pane.path, pane.archivePath || "", pane.archiveMember || "", name]
      .join("|")
      .toLocaleLowerCase();
  }

  function entryIcon(pane, entry, entryType, isArchiveFile, isVirtual) {
    let kind = "binary";
    let label = "Binary file";
    const name = String(entry.name || "");
    const cached = entry.contentKind || pane.fileKinds?.[fileKindKey(pane, name)];
    if (entryType === "disk") [kind, label] = ["disk", "Disk image"];
    else if (entryType === "rom-bank") [kind, label] = ["rom", "ROM bank"];
    else if (isVirtual) [kind, label] = ["catalogue", "Grouped results"];
    else if (entryType === "dir") [kind, label] = ["folder", pane.archivePath ? "Container folder" : "Folder"];
    else if (isArchiveFile || cached === "container" || archiveNamePattern.test(name)) [kind, label] = ["archive", "Archive or disk image"];
    else if (cached === "rom" || /\.(?:rom|img\.rom|tos)$/i.test(name) && /^tos/i.test(name)) [kind, label] = ["rom", "TOS ROM image"];
    else if (cached === "executable" || executableNamePattern.test(name)) [kind, label] = ["binary", "GEMDOS program"];
    else if (cached === "basic" || basicNamePattern.test(name)) [kind, label] = ["basic", "BASIC program"];
    else if (cached === "script" || scriptNamePattern.test(name)) [kind, label] = ["script", "Configuration file"];
    else if (cached === "system" || systemNamePattern.test(name)) [kind, label] = ["binary", "System or resource file"];
    else if (cached === "picture" || pictureNamePattern.test(name)) [kind, label] = ["file", "Picture"];
    else if (cached === "music" || musicNamePattern.test(name)) [kind, label] = ["file", "Music or sample"];
    else if (cached === "text" || textNamePattern.test(name) || /^(?:readme|read\.me|liesmich|lisez|install|history)(?:\.|$)/i.test(name)) [kind, label] = ["text", "Text file"];
    else if (entry.length === 0) [kind, label] = ["file", "Empty file"];
    return { kind, label, markup: FILE_ICONS[kind] };
  }

  return { entryIcon, fileKindKey, FILE_ICONS, PANE_ICONS, scriptNamePattern, archiveNamePattern, executableNamePattern };
})();
