window.AtariWorkspace = (() => {
  function newPaneState(image = null) {
    return {
      image,
      partition: null,
      side: image?.doubleSided ? 0 : null,
      partitionName: "",
      path: "",
      archivePath: null,
      archiveName: "",
      archiveMember: "",
      archiveKind: "",
      entries: [],
      capacity: null,
      selected: null,
      selection: [],
      selectionAnchor: null,
      loading: Boolean(image),
      requestToken: 0,
      menuDetected: false,
      fileKinds: {},
      windowState: null,
      menuDetectionPending: Boolean(image?.kind === "hd")
    };
  }

  // A GEMDOS volume: a floppy image, or one partition of an AHDI drive once
  // the partition has been chosen.
  const isGemdosPane = pane => (
    pane?.image?.kind === "gemdos"
    || (pane?.image?.kind === "hd" && pane.partition !== null)
  );

  // A saved workspace written before the separator changed spells the volume
  // root "$" or ":". The root is the empty path now, so those are folded back.
  function restoredGemdosPath(saved) {
    const path = typeof saved?.path === "string" ? saved.path : "";
    return path === "$" || path === ":" ? "" : path;
  }

  function normalisePage(value) {
    const cleaned = String(value || "").trim().replace(/^(?:&|\$|0x)/i, "").toUpperCase();
    return cleaned.replace(/^0+(?=[0-9A-F])/, "") || "0";
  }

  // GEMDOS separates path components with a backslash and names a drive with
  // a letter and a colon, so "C:\GAMES\ELITE" is the folder ELITE inside
  // GAMES on drive C. The root of a volume is the empty path, shown as "C:\"
  // when a drive letter is known. A forward slash is accepted on input,
  // because host paths and older saved workspaces use one, and a full stop
  // is an ordinary character in an 8.3 name.
  function splitPath(path) {
    const text = String(path ?? "").trim();
    if (text === "" || text === "$" || text === ":" || text === "/" || text === "\\") return [];
    return text.replace(/^[A-Za-z]:/, "").replace(/^[$:]/, "").split(/[\\/]/).filter(Boolean);
  }

  function fullPath(directory, name) {
    const leaf = String(name ?? "").replace(/^[\\/]+|[\\/]+$/g, "");
    const parts = splitPath(directory);
    return leaf ? [...parts, leaf].join("\\") : parts.join("\\");
  }

  function parentPath(path) {
    return splitPath(path).slice(0, -1).join("\\");
  }

  // The path as TOS would print it, with the drive letter when one is known.
  function drivePath(letter, path) {
    const parts = splitPath(path);
    const drive = String(letter || "").trim().toUpperCase().replace(/:$/, "");
    return drive ? `${drive}:\\${parts.join("\\")}` : parts.join("\\");
  }

  function selectionKeys(pane) {
    if (Array.isArray(pane.selection) && pane.selection.length) {
      return pane.selection.map(String);
    }
    return pane.selected == null ? [] : [String(pane.selected)];
  }

  function setSelection(pane, keys, anchor = null) {
    pane.selection = [...new Set(keys.map(String))];
    pane.selected = pane.selection.length === 1 ? pane.selection[0] : null;
    pane.selectionAnchor = anchor ?? pane.selection.at(-1) ?? null;
  }

  const entrySelectionKey = entry => String(entry.partition ?? entry.path ?? entry.name);
  const pathNameWithoutExtension = value => String(value || "").replace(/\.[^.]+$/, "");

  return {
    drivePath,
    entrySelectionKey,
    fullPath,
    splitPath,
    isGemdosPane,
    newPaneState,
    normalisePage,
    parentPath,
    pathNameWithoutExtension,
    restoredGemdosPath,
    selectionKeys,
    setSelection,
    // The names app.js and workspace-persistence.js still import.
  };
})();
