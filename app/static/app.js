const {
  drivePath,
  entrySelectionKey,
  fullPath,
  isGemdosPane,
  newPaneState,
  normalisePage,
  parentPath,
  pathNameWithoutExtension,
  restoredGemdosPath,
  selectionKeys,
  setSelection,
} = window.AtariWorkspace;
const { entryIcon, fileKindKey, FILE_ICONS, PANE_ICONS } = window.AtariFileVisuals;
const { newUuid } = window.AtariIdentifiers;
const { attributeFlags, attributeHex, formatAttributes, formatDatestamp, parseDatestamp } = window.AtariMetadata;
const {
  ignoredFolderFile,
  normaliseAttributes,
  targetNameRule,
} = window.AtariImportPlanning;

const panes = [newPaneState()];
let platformContract = { host: "web", hostCapabilities: [] };
let applicationVersion = "development";
let applicationEngine = "atarinut";

function hasHostCapability(capability) {
  return platformContract.hostCapabilities?.includes(capability) || false;
}

const {
  alertNotice,
  api: rawApi,
  uploadApi: rawUploadApi,
  confirmChoice,
  esc,
  humanSize,
  modal,
  modalContent,
  overlayDialog,
  promptValue,
  setModalAbort,
  setModalProgress,
  showModal,
  toast,
  trapFocus,
} = window.AtariUI;
const { archiveCrumbs, capacityMarkup, crumbs, exportAvailability, paneFormat } = window.AtariPaneView.create({ esc, humanSize });
const { folderTargetPlans } = window.AtariTransferPlanning.create({ targetNameRule });
const { confirmPageOverride } = window.AtariSafetyDialogs.create({ esc, normalisePage, trapFocus });
let collectionCatalogue = window.AtariCollectionCatalogue.create({ uuid: newUuid });
const collectionRevisionsSeen = new Map();
const showHelp = window.AtariHelp.create({ showModal, modalContent });
const showAbout = window.AtariAbout.create({
  showModal,
  esc,
  context: () => ({ version: applicationVersion, engine: applicationEngine, host: platformContract.host }),
});
const formats = window.AtariFormats;
let persistentStorageChanged = () => {};
const persistentStorage = {
  get length() { return localStorage.length; },
  key: index => localStorage.key(index),
  getItem: key => localStorage.getItem(key),
  setItem(key, value) { localStorage.setItem(key, value); persistentStorageChanged(); },
  removeItem(key) { localStorage.removeItem(key); persistentStorageChanged(); },
  clear() { localStorage.clear(); persistentStorageChanged(); },
};
const OPEN_PANES_STORAGE_KEY = "atari-file-forge-dynamic-panes";
const EDITOR_DOCUMENTS_STORAGE_KEY = "atari-file-forge-editor-documents-v1";
const MAX_RETAINED_EDITOR_DOCUMENTS = 24;
const MAX_RETAINED_EDITOR_DRAFT = 512 * 1024;
let workspaceClipboard = null;
let clipboardMutationInProgress = false;
const editorWorkspace = window.AtariEditorWorkspace.create({
  storage: sessionStorage,
  key: EDITOR_DOCUMENTS_STORAGE_KEY,
  maxDocuments: MAX_RETAINED_EDITOR_DOCUMENTS,
  maxDraftBytes: MAX_RETAINED_EDITOR_DRAFT,
});
const editorDocuments = editorWorkspace.state.documents;
const persistEditorDocuments = editorWorkspace.persist;
editorWorkspace.restore();

const workspacePersistence = window.AtariWorkspacePersistence.create({
  panes,
  storage: persistentStorage,
  storageKey: OPEN_PANES_STORAGE_KEY,
  newPaneState,
  restoredGemdosPath,
  api,
  rebuildPaneHosts,
  reconcilePaneWindows: () => paneWindowManager.reconcile(),
  renderPane,
  acceptImage,
  loadDirectory,
  editorWorkspace,
  activateEditorDocument,
  toast,
});
const rememberOpenPanes = workspacePersistence.remember;
const restoreOpenPanes = workspacePersistence.restore;
const paneWindowManager = window.AtariPaneWindowManager.create({
  container: document.querySelector(".panes"),
  taskbar: document.querySelector("#paneTaskbar"),
  panes,
  paneLabel,
  onChange: rememberOpenPanes,
});

function editorDocumentKey(index, pane, path) {
  return [index, pane.image?.id || "", pane.partition ?? "-", pane.side ?? "-", path].join("|");
}

function captureActiveEditorDocument() {
  if (!editorWorkspace.state.active) return;
  const document = editorDocuments.get(editorWorkspace.state.active);
  const textarea = modalContent.querySelector(".source-editor .source-content");
  if (!document || !textarea) return;
  document.draft = textarea.value;
  document.savedValue = textarea.dataset.savedValue ?? textarea.value;
  document.selectionStart = textarea.selectionStart;
  document.selectionEnd = textarea.selectionEnd;
  document.scrollTop = textarea.scrollTop;
  document.scrollLeft = textarea.scrollLeft;
  persistEditorDocuments();
}

function retainEditorDocument(index, pane, entry, path, view = "source") {
  captureActiveEditorDocument();
  const key = editorDocumentKey(index, pane, path);
  const existing = editorDocuments.get(key) || {};
  editorDocuments.set(key, {
    ...existing, key, index, imageId: pane.image.id, imageName: pane.image.name,
    path, directory: pane.path, name: entry.name, partition: pane.partition, side: pane.side, view,
  });
  editorWorkspace.state.active = key;
  persistEditorDocuments();
  return editorDocuments.get(key);
}

async function activateEditorDocument(key, force = false) {
  if (key === editorWorkspace.state.active && !force) return;
  captureActiveEditorDocument();
  const document = editorDocuments.get(key);
  if (!document) return;
  const pane = panes[document.index];
  if (!pane?.image || pane.image.id !== document.imageId) {
    editorDocuments.delete(key);
    persistEditorDocuments();
    return toast("That image is no longer open.", true);
  }
  pane.partition = document.partition;
  pane.side = document.side;
  pane.path = document.directory || "";
  await loadDirectory(document.index);
  await openFileEditor(document.index, document.name, null, document.path);
}

function installEditorDocumentTabs(root, pane) {
  if (!root || !editorWorkspace.state.active) return;
  root.querySelector(".editor-document-tabs")?.remove();
  const relevant = [...editorDocuments.values()].filter(document => document.imageId === pane.image.id);
  const bar = document.createElement("nav");
  bar.className = "editor-document-tabs";
  bar.setAttribute("aria-label", "Open files in this image");
  bar.innerHTML = `<div>${relevant.map(document => `<button type="button" data-editor-document="${esc(document.key)}" class="${document.key === editorWorkspace.state.active ? "active" : ""}" title="${esc(document.path)}"><span>${esc(document.name)}</span>${document.draft != null && document.draft !== document.savedValue ? "<i>●</i>" : ""}<b data-editor-document-close="${esc(document.key)}" aria-label="Close ${esc(document.name)}">×</b></button>`).join("")}</div><button type="button" data-editor-navigate-image title="Search and open another file in this image">Open from image…</button>`;
  root.querySelector("header")?.after(bar);
  bar.querySelectorAll("[data-editor-document]").forEach(button => button.addEventListener("click", event => {
    if (event.target.closest("[data-editor-document-close]")) return;
    activateEditorDocument(button.dataset.editorDocument);
  }));
  bar.querySelectorAll("[data-editor-document-close]").forEach(button => button.addEventListener("click", async event => {
    event.stopPropagation();
    captureActiveEditorDocument();
    const key = button.dataset.editorDocumentClose;
    const document = editorDocuments.get(key);
    if (document?.draft != null && document.draft !== document.savedValue
      && !await confirmChoice("Discard unsaved changes?", `${document.name} has changes that have not been written back to the image.`, { confirmLabel: "Close and discard", danger: true })) return;
    editorDocuments.delete(key);
    persistEditorDocuments();
    if (key !== editorWorkspace.state.active) return installEditorDocumentTabs(root, pane);
    editorWorkspace.state.active = null;
    persistEditorDocuments();
    const next = [...editorDocuments.values()].find(item => item.imageId === pane.image.id);
    if (next) await activateEditorDocument(next.key); else modal.close();
  }));
  bar.querySelector("[data-editor-navigate-image]")?.addEventListener("click", async () => {
    const result = await editorImageSearch(pane);
    if (!result) return;
    if (result.partition != null) pane.partition = Number(result.partition);
    if (result.side != null) pane.side = Number(result.side);
    pane.path = parentPath(result.path);
    await loadDirectory(panes.indexOf(pane));
    await openFileEditor(panes.indexOf(pane), result.name, null, result.path);
  });
}

function clearWorkspaceClipboard(message = "", rerender = true) {
  if (!workspaceClipboard) return;
  workspaceClipboard = null;
  document.querySelectorAll(".clipboard-cut").forEach(row => row.classList.remove("clipboard-cut"));
  if (rerender) panes.forEach((_pane, index) => renderPane(index, true));
  if (message) toast(message);
}

function api(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  if (!["GET", "HEAD"].includes(method) && workspaceClipboard && !clipboardMutationInProgress) {
    clearWorkspaceClipboard("Clipboard cleared because another change was started.");
  }
  return rawApi(url, options);
}

function uploadApi(url, formData, options = {}) {
  if (workspaceClipboard && !clipboardMutationInProgress) {
    clearWorkspaceClipboard("Clipboard cleared because another change was started.");
  }
  return rawUploadApi(url, formData, options);
}

//  How long the pointer may sit outside an open menu before it closes. A menu
//  panel and its summary are separate boxes with a gap between them, and a
//  submenu opens a column the pointer crosses corners to reach, so closing the
//  instant the pointer leaves would shut the menu during ordinary use. A short
//  grace period is long enough to cross those gaps and short enough that the
//  menu still feels as though it closes when you move away from it.
const MENU_CLOSE_DELAY = 260;

/** Close a details-based menu when the pointer moves off it, and tidy up.
 *
 * A menu that stays open until its own heading is clicked again leaves a panel
 * covering the file list while the operator works somewhere else, and reads as
 * though it is stuck. This gives every menu the behaviour a menu is expected
 * to have: it closes when the pointer moves away, when something outside it is
 * clicked, when Escape is pressed and when a command inside it is chosen.
 *
 * The pointer rule only arms once the pointer has actually been inside the
 * menu, so a menu opened from the keyboard is not closed by a mouse resting
 * somewhere else on the screen.
 */
function wireDismissibleMenu(menu) {
  if (!menu || menu.dataset.dismissWired === "yes") return;
  menu.dataset.dismissWired = "yes";
  let closeTimer = null;
  const cancelClose = () => { clearTimeout(closeTimer); closeTimer = null; };
  const close = () => { cancelClose(); menu.open = false; };
  menu.addEventListener("pointerenter", cancelClose);
  menu.addEventListener("pointerleave", event => {
    // A pointerleave raised while a native control such as a <select> has the
    // pointer captured is not the operator moving away from the menu.
    if (!menu.open || event.pointerType === "" ) return;
    cancelClose();
    closeTimer = setTimeout(close, MENU_CLOSE_DELAY);
  });
  menu.addEventListener("toggle", () => { if (!menu.open) cancelClose(); });
  // Choosing a command is the end of the menu's job, whether or not the pane
  // is re-rendered afterwards.
  menu.addEventListener("click", event => {
    if (event.target.closest("summary")) return;
    if (event.target.closest("button, a")) close();
  });
}

/** Close every open menu, except one being deliberately left alone. */
function closeOpenMenus(except = null) {
  document.querySelectorAll(".tool-menu[open], .top-help-menu[open]").forEach(menu => {
    if (menu !== except && !menu.contains(except)) menu.open = false;
  });
}

document.addEventListener("pointerdown", event => {
  const inside = event.target.closest(".tool-menu, .top-help-menu");
  closeOpenMenus(inside);
});
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  const open = document.querySelector(".tool-menu[open]");
  if (!open) return;
  open.open = false;
  open.querySelector(":scope > summary")?.focus();
});

function fitPaneMenus(host) {
  const menus = [...host.querySelectorAll(".tool-menu")];
  menus.forEach(menu => {
    wireDismissibleMenu(menu);
    menu.addEventListener("toggle", () => {
      if (!menu.open) return;
      // Only one menu at a time, across every pane, not just this one.
      closeOpenMenus(menu);
      requestAnimationFrame(() => {
        const panel = menu.querySelector(":scope > .tool-menu-panel");
        if (!panel) return;
        const available = Math.max(140, window.innerHeight - panel.getBoundingClientRect().top - 10);
        panel.style.setProperty("--menu-available-height", `${available}px`);
        panel.classList.toggle("tool-menu-panel-right", panel.getBoundingClientRect().right > window.innerWidth - 8);
      });
    });
  });
}

function updateAddPaneButton() {
  const button = document.querySelector("#addPaneButton");
  if (!button) return;
  button.disabled = false;
  button.title = "Add another work pane";
  button.setAttribute("aria-label", button.title);
}

function rebuildPaneHosts() {
  const host = document.querySelector(".panes");
  host.dataset.count = String(panes.length);
  host.querySelectorAll(":scope > .pane").forEach(pane => pane.remove());
  const fragment = document.createDocumentFragment();
  panes.forEach((_pane, index) => {
    const pane = document.createElement("article");
    pane.className = "pane";
    pane.dataset.pane = String(index);
    fragment.append(pane);
  });
  host.prepend(fragment);
  panes.forEach((_pane, index) => renderPane(index));
  paneWindowManager.reconcile();
  updateAddPaneButton();
}

function addPane() {
  panes.push(newPaneState());
  rebuildPaneHosts();
  const index = panes.length - 1;
  paneWindowManager.bringToFront(index);
  rememberOpenPanes();
  return index;
}

function otherPaneIndexes(index) {
  return panes.map((_pane, offset) => offset).filter(offset => offset !== index);
}

function preferredDestinationPane(index) {
  return otherPaneIndexes(index).find(offset => !panes[offset].image)
    ?? otherPaneIndexes(index)[0];
}

function paneLabel(index) {
  return `Pane ${index + 1}${panes[index].image ? ` · ${panes[index].image.name}` : " · Empty"}`;
}

//: The floppy geometries a TOS machine can format, smallest first. A single
//: sided drive can only reach the first three; every double sided drive can
//: read all of the 720K, 800K and 880K formats, and only the later Ajax
//: controller reaches 1.44M.
const FLOPPY_GEOMETRIES = Object.freeze([
  { value: "ss-360k", label: "360K", size: 368640, singleSided: true, hfe: "" },
  { value: "ss-400k", label: "400K", size: 409600, singleSided: true, hfe: "hfe-st-400k" },
  { value: "ss-440k", label: "440K", size: 450560, singleSided: true, hfe: "hfe-st-440k" },
  { value: "ds-720k", label: "720K", size: 737280, singleSided: false, hfe: "hfe-st-720k" },
  { value: "ds-800k", label: "800K", size: 819200, singleSided: false, hfe: "hfe-st-800k" },
  { value: "ds-880k", label: "880K", size: 901120, singleSided: false, hfe: "hfe-st-880k" },
  { value: "hd-1440k", label: "1.44M", size: 1474560, singleSided: false, hfe: "hfe-st-1440k" },
]);

function floppyGeometryForSize(size) {
  const bytes = Number(size || 0);
  return [...FLOPPY_GEOMETRIES].reverse().find(entry => bytes >= entry.size) || FLOPPY_GEOMETRIES[3];
}

function matchingBlankImageFormat(pane) {
  const image = pane.image;
  if (!image) return { value: "ds-720k", label: "720K floppy" };
  if (image.kind === "hd") return { value: "hd", label: "Hard drive" };
  if (image.kind === "rom") return { value: "rom", label: "ROM" };
  if (image.kind === "tosrom") return { value: "cartridge", label: "Cartridge ROM" };
  if (image.kind === "gemdos") {
    if (image.hardDisk || image.targetHardware === "hd") return { value: "hd", label: "Hard drive" };
    if (image.targetHardware === "volume") return { value: "volume", label: "Bare volume" };
    // A GEMDOS floppy is described by its geometry alone: FAT12 on every one
    // of them, so a new blank simply matches the shape of the open disk and
    // stays in the container it arrived in.
    const geometry = floppyGeometryForSize(image.size);
    if (image.containerFormat === "hfe" && geometry.hfe) {
      return { value: geometry.hfe, label: `HFE ${geometry.label} floppy` };
    }
    return { value: geometry.value, label: `${geometry.label} floppy` };
  }
  return { value: "ds-720k", label: "720K floppy" };
}

//: The floppy containers a pane can open. Each holds the sectors of one
//: disk in its own packing, so a pane shows the container project rather
//: than a mounted volume until the sectors are converted.
const CONTAINER_KINDS = Object.freeze(["msa", "dim", "stx"]);
//: Media whose bytes this build never writes back: a Pasti capture keeps
//: information a sector image cannot hold, and a CD and a TOS ROM are read
//: from rather than edited.
const READ_ONLY_KINDS = Object.freeze(["stx", "iso", "tosrom"]);
const CONTAINER_LABELS = Object.freeze({
  msa: "Magic Shadow Archiver image",
  dim: "FastCopy Pro image",
  stx: "Pasti capture",
});

//: The badge colour a pane wears. A mounted partition looks like the GEMDOS
//: volume it is, and a TOS ROM shares the ROM colour.
function paneFormatClass(pane) {
  const kind = pane.image?.kind || "";
  if (kind === "hd" && pane.partition !== null) return "gemdos";
  if (kind === "tosrom") return "rom";
  return kind;
}

//: The one line that describes a partition table: which scheme it uses, how
//: many partitions it declares, and whether the drive was written with its
//: words the other way round, which some ACSI adapters do.
const PARTITION_SCHEMES = Object.freeze({
  ahdi: "AHDI partition table",
  xgm: "AHDI partition table with an XGM extension",
  icd: "ICD partition table",
  mbr: "MBR partition table",
});

//: What the pane footer says while a drive is showing its partition table:
//: the invitation, plus the size the drive declares when the table records
//: one, because a table that disagrees with the file it lives in is the
//: first thing worth knowing about a drive that will not mount.
function paneTableDescription(pane) {
  const declared = Number(pane.partitionTable?.hdSize || 0);
  return declared > 0
    ? `Select a partition to browse the volume it mounts · the table declares ${humanSize(declared)}`
    : "Select a partition to browse the volume it mounts";
}

//: The root directory of a GEMDOS volume is a fixed table rather than a file
//: of its own, so it runs out of entries long before the disk runs out of
//: space: 112 on a 720K floppy and 224 on a 1.44M one. A folder further down
//: has no such limit, so the count is only shown at the root.
function rootEntryNote(pane) {
  const limit = Number(pane.image?.filesystemCapabilities?.directoryEntryLimit || 0);
  if (!limit || pane.path !== "" || pane.archivePath) return "";
  return ` · ${pane.entries.length} of ${limit} root entries`;
}

function partitionTableLabel(table) {
  if (!table) return "Partition table";
  const scheme = PARTITION_SCHEMES[String(table.scheme || "").toLowerCase()] || "Partition table";
  const count = Array.isArray(table.partitions) ? table.partitions.length : null;
  return [
    scheme,
    count == null ? "" : `${count} partition${count === 1 ? "" : "s"}`,
    table.byteSwapped ? "byte-swapped" : "",
  ].filter(Boolean).join(" · ");
}

function paneDragHandle(index) {
  return `<button class="pane-drag-handle" type="button" title="Move pane ${index + 1}" aria-label="Move pane ${index + 1}"><b>⠿</b><small>${index + 1}</small></button>`;
}

function setLoading(index, value, message = "Reading disk…") {
  const displayMessage = typeof message === "object"
    ? (message.message || message.title || "Working…")
    : message;
  panes[index].loading = value;
  panes[index].loadingMessage = displayMessage;
  if (value && modal.open) setModalProgress(message);
  renderPane(index);
}

async function paneOperation(index, message, operation) {
  const pane = panes[index];
  setLoading(index, true, message);
  try {
    return await operation();
  } finally {
    if (panes[index] === pane) {
      pane.loading = false;
      pane.loadingMessage = "";
      renderPane(index);
    }
  }
}

const { guardedPaneAction, trackedPaneOperation } = window.AtariOperationUI.create({
  panes,
  api,
  setLoading,
  renderPane,
  modal,
  setModalAbort,
  setModalProgress,
  newUuid,
});

async function openHexEditor(index, initialOffset = 0, { host: requestedHost = null, onClose = null, afterSave = null, pageSize = 256 } = {}) {
  const pane = panes[index];
  const host = requestedHost || document.querySelector(`.pane[data-pane="${index}"]`);
  if (!pane?.image || !host || !window.AtariHexEditor) {
    return toast("The hex editor could not be opened.", true);
  }
  await window.AtariHexEditor.open({
    host,
    image: { ...pane.image },
    request: api,
    notify: toast,
    initialOffset,
    initialPageSize: pageSize,
    onSaved: updatedImage => {
      if (panes[index] === pane) {
        pane.image = updatedImage;
        rememberOpenPanes();
      }
      afterSave?.(updatedImage);
    },
  });
  if (panes[index] === pane) await onClose?.();
  if (panes[index] === pane) await refreshCurrentView(index);
}

//: How the drive declares its partitions: which table it carries, whether
//: its words are byte-swapped, and how large the drive says it is. It is
//: read alongside the partition listing so the pane can say what shape the
//: drive is in rather than only what is on it.
async function fetchPartitionTable(imageId) {
  try {
    return (await api(`/api/images/${imageId}/partition-table`)).partitionTable;
  } catch (_error) {
    return null;
  }
}

async function fetchCapacity(imageId, partition = null) {
  const query = new URLSearchParams();
  if (partition !== null) query.set("partition", partition);
  const encoded = query.toString();
  const suffix = encoded ? `?${encoded}` : "";
  try {
    return (await api(`/api/images/${imageId}/capacity${suffix}`)).capacity;
  } catch (_error) {
    return null;
  }
}

function selectedEntries(index) {
  const pane = panes[index];
  const keys = new Set(selectionKeys(pane));
  return pane.entries.filter(entry => keys.has(entrySelectionKey(entry)));
}

function entryImagePath(pane, entry) {
  return entry.path || fullPath(pane.path, entry.name);
}

function selectedEntry(index) {
  const entries = selectedEntries(index);
  return entries.length === 1 ? entries[0] : null;
}

function removePhysicalFloppyContextMenu() {
  document.querySelector(".physical-floppy-context-menu")?.remove();
}

function showPhysicalFloppyContextMenu(index, event, enabled) {
  event.preventDefault();
  removePhysicalFloppyContextMenu();
  const menu = document.createElement("div");
  menu.className = "physical-floppy-context-menu";
  menu.setAttribute("role", "menu");
  menu.style.left = `${Math.max(8, Math.min(event.clientX, window.innerWidth - 250))}px`;
  menu.style.top = `${Math.max(8, Math.min(event.clientY, window.innerHeight - 60))}px`;
  menu.innerHTML = `<button type="button" role="menuitem" ${enabled ? "" : "disabled"} title="${enabled ? "Write this image with Greaseweazle" : "Use the native Linux host to access physical hardware."}"><b>▣</b><span>Write physical floppy…</span></button>`;
  document.body.append(menu);
  const button = menu.querySelector("button");
  button.onclick = () => {
    removePhysicalFloppyContextMenu();
    guardedPaneAction(index, () => showPhysicalFloppyDialog(index));
  };
  button.focus();
  menu.onkeydown = keyEvent => {
    if (keyEvent.key === "Escape") {
      keyEvent.preventDefault();
      removePhysicalFloppyContextMenu();
      event.currentTarget.focus();
    }
  };
  const close = closeEvent => {
    if (!menu.contains(closeEvent.target)) removePhysicalFloppyContextMenu();
  };
  setTimeout(() => document.addEventListener("pointerdown", close, { once: true }), 0);
}

async function showPhysicalFloppyDialog(index) {
  const pane = panes[index];
  if (!pane?.image) return;
  if (!hasHostCapability("physical-floppy-write")) {
    return toast("Physical floppy access requires the native Linux host.", true);
  }
  const query = new URLSearchParams();
  showModal('<div class="analysis-loading compact"><span class="modal-progress-icon" aria-hidden="true">↻</span><h2>Checking Greaseweazle</h2><p>Finding the device and validating the selected image…</p></div>');
  try {
    const status = await api(`/api/desktop/images/${pane.image.id}/physical-floppy?${query}`);
    const verification = status.media.automaticVerification
      ? "Every written sector will be read back and verified automatically."
      : "This flux-level image cannot be verified with a sector read-back. Test the disk in suitable hardware afterwards.";
    const unavailable = status.available ? "" : `<div class="help-warning"><strong>Greaseweazle is not ready.</strong> ${esc(status.detail)}</div>`;
    // The capture formats and the geometries are whatever the desktop
    // endpoint reports, so a build that grows a format needs no change here.
    const captureFormats = status.media.captureFormats || status.captureFormats || [];
    const geometries = status.media.geometries || status.geometries || [];
    showModal(`<div class="analysis-dialog physical-floppy-dialog"><header><div><small>PHYSICAL MEDIA</small><h2>Write ${esc(status.media.name)}</h2></div></header>
      <p>This will write the current working image to a real floppy disk. Unsaved image changes are included.</p>
      <dl class="physical-floppy-summary"><div><dt>Image type</dt><dd>${esc(status.media.format)}</dd></div><div><dt>Verification</dt><dd>${status.media.automaticVerification ? "Automatic sector verification" : "Not available for flux images"}</dd></div></dl>
      ${unavailable}
      <label class="field"><span>Physical drive</span><select name="physicalDrive" ${status.available ? "" : "disabled"}>${status.drives.map(drive => `<option value="${esc(drive.id)}">${esc(drive.label)}</option>`).join("")}</select></label>
      ${captureFormats.length ? `<label class="field"><span>Written as</span><select name="captureFormat" ${status.available ? "" : "disabled"}>${captureFormats.map(format => `<option value="${esc(format.id)}">${esc(format.label)}</option>`).join("")}</select></label>` : ""}
      ${geometries.length ? `<label class="field" data-geometry-field><span>Geometry</span><select name="captureGeometry" ${status.available ? "" : "disabled"}>${geometries.map(geometry => `<option value="${esc(geometry.id)}">${esc(geometry.label)}</option>`).join("")}</select><small>A sector image carries no geometry of its own, so the tracks, sides and sectors have to be stated before the disk is cut.</small></label>` : ""}
      <div class="help-warning"><strong>This is destructive.</strong> All existing data on the disk in the selected drive will be overwritten. ${esc(verification)}</div>
      <label class="check-field physical-floppy-confirm"><input type="checkbox" name="physicalConfirmed" required ${status.available ? "" : "disabled"}> I understand that the physical disk will be overwritten.</label>
      <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button danger" value="write" ${status.available ? "" : "disabled"}>Write and ${status.media.automaticVerification ? "verify" : "finish unverified"}</button></div></div>`, async form => {
        const result = await trackedPaneOperation(
          index,
          `Writing ${status.media.name} to a physical floppy`,
          operationId => api(`/api/desktop/images/${pane.image.id}/physical-floppy`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              drive: form.get("physicalDrive"),
              format: form.get("captureFormat") || "",
              geometry: form.get("captureGeometry") || "",
              operationId,
            }),
          }),
          { abortMode: "physical" },
        );
        const verified = result.result.verified;
        showModal(`<div class="analysis-dialog physical-floppy-complete"><header><div><small>PHYSICAL MEDIA</small><h2>${verified ? "Disk written and verified" : "Disk written"}</h2></div></header>
          <p>${esc(result.media.name)} was written to drive ${esc(result.result.drive)}.</p>
          <div class="help-${verified ? "note" : "warning"}"><strong>${verified ? "Verification passed." : "Verification was not available."}</strong> ${verified ? "Greaseweazle confirmed every written track." : "Test this flux-derived disk in its target hardware before relying on it."}</div>
          <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div></div>`, null, { replace: true });
        return false;
      }, { replace: true });
    // A geometry only has to be stated for a sector image; a track or flux
    // capture already carries its own.
    const formatSelect = modalContent.querySelector('[name="captureFormat"]');
    const geometryField = modalContent.querySelector("[data-geometry-field]");
    if (formatSelect && geometryField) {
      const refreshGeometry = () => {
        geometryField.hidden = !["st", "msa"].includes(formatSelect.value);
      };
      formatSelect.addEventListener("change", refreshGeometry);
      refreshGeometry();
    }
  } catch (error) {
    modal.close();
    toast(`Could not prepare the physical write: ${error.message}`, true);
  }
}

function clipboardItemsForPane(index) {
  const pane = panes[index];
  if (!pane?.image) return [];
  // A partition table has nothing to put on a clipboard: partitions are
  // declared by the drive, not moved between drives.
  if (pane.image.kind === "hd" && pane.partition === null) return [];
  if (pane.image.kind === "rom") {
    return selectedEntries(index).map(entry => ({
      pane: index,
      image: pane.image.id,
      partition: null,
      side: null,
      path: `bank:${entry.bank}`,
      name: `BANK${String(entry.bank).padStart(3, "0")}`,
      length: Number(entry.length || 0),
      recursive: false,
      romBank: Number(entry.bank),
    }));
  }
  return selectedEntries(index)
    .filter(entry => !entry.virtual && entry.type !== "partition")
    .map(entry => ({
      pane: index,
      image: pane.image.id,
      partition: pane.partition,
      side: pane.side,
      path: entryImagePath(pane, entry),
      name: entry.name,
      length: Number(entry.length || 0),
      recursive: entry.type === "dir" || entry.type === "directory",
    }));
}

function rowIsPendingCut(pane, entry) {
  if (!workspaceClipboard || workspaceClipboard.mode !== "cut") return false;
  const path = entryImagePath(pane, entry).toLowerCase();
  return workspaceClipboard.kind === "files"
    && workspaceClipboard.items.some(item =>
      item.image === pane.image.id
      && item.partition === pane.partition
      && item.side === pane.side
      && String(item.path).toLowerCase() === path
    );
}

function canPasteIntoPane(pane) {
  if (!workspaceClipboard || !pane?.image || pane.image.readOnly || READ_ONLY_KINDS.includes(pane.image.kind) || CONTAINER_KINDS.includes(pane.image.kind)) return false;
  // A partition table is not a place files can be pasted; a volume always is.
  return !(pane.image.kind === "hd" && pane.partition === null);
}

function selectRow(index, key, { toggle = false, range = false } = {}) {
  const pane = panes[index];
  const rowKeys = pane.entries.map(entrySelectionKey);
  const current = new Set(selectionKeys(pane));
  if (range && pane.selectionAnchor != null && rowKeys.includes(String(pane.selectionAnchor))) {
    const start = rowKeys.indexOf(String(pane.selectionAnchor));
    const end = rowKeys.indexOf(String(key));
    const keys = rowKeys.slice(Math.min(start, end), Math.max(start, end) + 1);
    setSelection(pane, toggle ? [...current, ...keys] : keys, pane.selectionAnchor);
    return;
  }
  if (toggle) {
    if (current.has(String(key))) current.delete(String(key)); else current.add(String(key));
    setSelection(pane, [...current], key);
    return;
  }
  setSelection(pane, [key], key);
}

function emptyMarkup() {
  return document.querySelector("#emptyPane").innerHTML;
}

function loadingMarkup(pane) {
  if (!pane.loading) return "";
  const determinate = pane.progressTotal > 0;
  const progress = determinate
    ? Math.min(100, Math.round(100 * (pane.progressCurrent || 0) / pane.progressTotal))
    : 0;
  return `<div class="loading" role="status" aria-live="polite">
    <span>${esc(pane.loadingMessage || "Reading disk…")}</span>
    <span class="progress${determinate ? " determinate" : ""}" ${determinate ? `style="--operation-progress:${progress}%"` : ""}><i></i></span>
  </div>`;
}

function renderPane(index, preserveScroll = false) {
  const pane = panes[index];
  if (pane.image && collectionCatalogue.available && collectionRevisionsSeen.get(pane.image.id) !== pane.image.revision) {
    collectionRevisionsSeen.set(pane.image.id, pane.image.revision);
    collectionCatalogue.markStale(pane.image).catch(() => {});
  }
  const host = document.querySelector(`.pane[data-pane="${index}"]`);
  const previousScrollTop = preserveScroll ? (host.querySelector(".list-wrap")?.scrollTop || 0) : 0;
  if (!pane.image) {
    host.className = "pane";
    host.innerHTML = `${paneDragHandle(index)}${emptyMarkup()}${loadingMarkup(pane)}`;
    host.querySelector(".pane-open").onclick = () => chooseImage(index);
    host.querySelector(".pane-new").onclick = () => showCreateImageModal(index);
    host.querySelector(".pane-recover").onclick = () => recoverPreviousSession(index);
    host.querySelector(".close-empty-pane").onclick = () => closePane(index);
    if (pane.loading) {
      host.querySelectorAll("button").forEach(button => {
        button.disabled = true;
      });
    }
    wireDropZone(host, index);
    paneWindowManager.mount(index, host);
    rememberOpenPanes();
    return;
  }

  const selected = selectedEntry(index);
  const selectedKeys = new Set(selectionKeys(pane));
  const isPartitionIndex = pane.image.kind === "hd" && pane.partition === null;
  const isDrive = pane.image.kind === "hd";
  //: A floppy container holds the sectors of one disk rather than a mounted
  //: volume, so it is browsed as a project and converted rather than edited
  //: in place. A Pasti capture is read-only by nature.
  const isContainer = CONTAINER_KINDS.includes(pane.image.kind);
  const isRom = pane.image.kind === "rom";
  const isTosRom = pane.image.kind === "tosrom";
  const isHardDiskVolume = pane.image.kind === "gemdos" && Boolean(pane.image.hardDisk);
  // Staging a disk, installing a title or preparing a drive all need a
  // writable GEMDOS volume to work on.
  const acceptsInstall = paneAcceptsInstall(pane);
  const isArchive = Boolean(pane.archivePath);
  const isGemdos = isGemdosPane(pane);
  // Every GEMDOS volume nests folders, so the only views without them are
  // the ones with no directory structure at all.
  const supportsFolders = !isPartitionIndex && !isContainer && !isArchive && !isRom && !isTosRom;
  const canFolder = supportsFolders && !pane.image.readOnly;
  const canEdit = !isPartitionIndex && !isContainer && !isArchive && !pane.image.readOnly;
  const kind = paneFormatClass(pane);
  const driveLetter = pane.partitionName || pane.image.driveLetter || "";
  const location = isArchive
    ? `${pane.archiveName} · \\${pane.archiveMember || ""}`
    : isPartitionIndex
    ? partitionTableLabel(pane.partitionTable)
    : isContainer
      ? `${CONTAINER_LABELS[pane.image.kind] || "Floppy container"} · ${pane.image.readOnly ? "read-only" : "convert to browse"}`
      : isRom
        ? `${pane.image.rom?.platform || "Atari"} · ${pane.image.rom?.bankCount || 0} bank(s)`
      : isTosRom
        ? `${pane.image.tosrom?.title || "TOS ROM"} · version ${pane.image.tosrom?.version ?? 0} · read-only segments`
      : pane.partition !== null
        ? `${pane.partitionName || `Partition ${pane.partition}`} · ${drivePath(driveLetter, pane.path)}`
        : pane.image.filesystemCapabilities
          ? `${pane.image.filesystemCapabilities.format} · ${drivePath(driveLetter, pane.path)}${rootEntryNote(pane)}`
          : `Volume root · ${drivePath(driveLetter, pane.path)}${rootEntryNote(pane)}`;
  const hasParentEntry = isArchive || (!isPartitionIndex && !isContainer && !isRom && (
    pane.partition !== null || pane.path !== ""
  ));
  const parentRow = hasParentEntry ? `<tr class="file-row parent-row" aria-label="Parent directory" tabindex="0" draggable="false" data-parent="1" data-key=".." data-name=".." data-type="dir" data-partition="">
    <td class="file-name-cell"><div class="file-name-wrap"><span class="file-icon dir" title="Parent directory">${FILE_ICONS.folderUp}</span><strong>..</strong></div></td>
    <td class="meta">Parent directory</td>
    <td class="meta">-</td>
    <td class="meta address-cell">-</td>
    <td><span class="pill">-</span></td>
  </tr>` : "";
  const rows = pane.entries.map(entry => {
    const entryType = entry.type === "directory" ? "dir" : entry.type;
    const isDir = entryType === "dir";
    const isVirtual = Boolean(entry.virtual);
    const isArchiveFile = Boolean(entry.archive);
    const visual = entryIcon(pane, entry, entryType, isArchiveFile, isVirtual);
    const icon = visual.markup;
    const size = entryType === "partition" ? humanSize(entry.length) : isVirtual ? "Catalogue group" : isDir ? `${entry.length || 0} items` : humanSize(entry.length);
    const detail = entryType === "partition"
      ? entry.format || "Unknown filing system"
      : entry.filetype || entry.contentKind || "-";
    const attr = entryType === "partition"
      ? (entry.bootable ? "Boot" : "-")
      : entry.attributes || (entry.attr != null ? formatAttributes(entry.attr) : "");
    const entryKey = entrySelectionKey(entry);
    const rowActionable = !isArchive && !isVirtual && !pane.image.readOnly && !isContainer && !isPartitionIndex && canEdit;
    const accessActionable = rowActionable;
    const downloadable = !isPartitionIndex && !isDir && !isVirtual && !isRom;
    const openHint = isArchiveFile ? ' title="Double-click to browse this archive"' : downloadable ? ' title="Double-click to open"' : "";
    const multiSelection = selectedKeys.size > 1;
    const hideGroupAction = multiSelection && !selectedKeys.has(entryKey);
    const actionName = isPartitionIndex ? `partition ${entry.name}` : isRom ? `bank ${entry.bank} · ${entry.name}` : entry.name;
    const downloadAction = downloadable ? `<button class="row-action row-download" type="button" draggable="false" title="${isArchive ? "Export archive member" : `Download ${esc(actionName)} with its metadata`}" aria-label="${isArchive ? `Export ${esc(actionName)}` : `Download ${esc(actionName)}`}">⇩</button>` : "";
    const rowActions = rowActionable || isRom ? `<span class="row-actions">
      ${isRom ? `<button class="row-action row-rom-inspect" type="button" draggable="false" title="Decode ${esc(actionName)}" aria-label="Decode ${esc(actionName)}">ⓘ</button>` : ""}
      ${!isRom || entry.header ? `<button class="row-action row-rename" type="button" draggable="false" title="Rename ${esc(actionName)}" aria-label="Rename ${esc(actionName)}" ${multiSelection ? "hidden" : ""}>✎</button>` : ""}
      ${rowActionable ? `<button class="row-action delete row-delete" type="button" draggable="false" title="Delete ${esc(actionName)}" aria-label="Delete ${esc(actionName)}" ${hideGroupAction ? "hidden" : ""}>×</button>` : ""}
    </span>` : "";
    const accessCell = `<td class="access-cell" data-label="Attributes"><span class="pill" title="GEMDOS attributes · read-only, hidden, system, volume label, directory, archive">${esc(attr || detail)}</span>${accessActionable && !isRom ? `<span class="access-actions" ${hideGroupAction ? "hidden" : ""}>
      <button class="row-action row-read-write" type="button" draggable="false" title="Clear the read-only attribute · ${esc(actionName)}" aria-label="Clear the read-only attribute on ${esc(actionName)}">◇</button>
      <button class="row-action row-read-only" type="button" draggable="false" title="Set the read-only attribute · ${esc(actionName)}" aria-label="Set the read-only attribute on ${esc(actionName)}">◆</button>
    </span>` : ""}</td>`;
    const editableMetadata = !isVirtual && !isArchive && !pane.image.readOnly && !isContainer && !isRom && !isTosRom;
    const romHeader = entry.header || null;
    const romOffset = Number.isFinite(Number(entry.fileOffset)) ? Number(entry.fileOffset) : Number(entry.bank || 0) * Number(pane.image.rom?.bankSize || entry.length || 0);
    // A cartridge is decoded at $FA0000 on every ST-family machine; anything
    // else is a bank of bytes with no fixed home in the address space.
    const romMapped = pane.image.rom?.platform === "cartridge" && Number(entry.length) <= 131072
      ? `Mapped &amp;FA0000-&amp;${(0xFA0000 + Math.max(0, Number(entry.length) - 1)).toString(16).toUpperCase().padStart(6, "0")}`
      : "No fixed CPU mapping";
    const romPurpose = entry.empty
      ? "Available erased bank"
      : romHeader
        ? `${esc(romHeader.roles)} · ${esc(romHeader.processor)}`
        : entry.extensionHeader
          ? "Cartridge or expansion ROM header"
          : "Unrecognised header / raw bytes";
    const romEntries = romHeader
      ? [["Language", romHeader.languageEntry], ["Service", romHeader.serviceEntry]].filter(([_label, value]) => Number.isFinite(Number(value))).map(([label, value]) => `${label} &amp;${Number(value).toString(16).toUpperCase()}`).join(" · ")
      : "";
    const romIdentityDetail = entry.empty
      ? "Filled with the configured erased byte"
      : romHeader
        ? [romHeader.version ? `Version ${esc(romHeader.version)}` : "", romHeader.copyright ? esc(romHeader.copyright) : ""].filter(Boolean).join(" · ")
        : "Open Info to inspect strings, structures and possible modules";
    const romUsage = entry.empty
      ? `0 programmed · ${humanSize(entry.length)}`
      : `${humanSize(Number(entry.programmedBytes ?? entry.length))} programmed · ${Number(entry.programmedPercent ?? 100).toLocaleString()}%`;
    const romMatches = entry.matchingBanks?.length ? `Identical to bank${entry.matchingBanks.length === 1 ? "" : "s"} ${entry.matchingBanks.join(", ")}` : "Unique bank contents";
    const cells = isPartitionIndex
      ? `<td class="file-name-cell"><div class="file-name-wrap"><span class="file-icon ${visual.kind}" title="${esc(visual.label)}">${icon}</span><strong>${esc(entry.name)}</strong></div></td>
      <td class="meta">${esc(entry.identifier || entry.filetype || "Unknown")}</td>
      <td class="meta">${esc(humanSize(entry.length))}</td>
      <td class="meta">${esc(entry.format || "Unknown filing system")}</td>
      <td><span class="pill">${entry.bootable ? `Boot priority ${Number(entry.bootPriority ?? 0)}` : "No"}</span></td>`
      : isRom ? `<td class="rom-bank-cell" data-label="Bank and address"><strong>Bank ${String(entry.bank).padStart(3, "0")}</strong><small>File &amp;${romOffset.toString(16).toUpperCase().padStart(6, "0")}</small><small>${romMapped}</small></td>
        <td class="file-name-cell rom-identity-cell" data-label="Identity"><div class="file-name-wrap"><span class="file-icon ${visual.kind}" title="${esc(visual.label)}">${icon}</span><strong>${esc(entry.name)}</strong>${rowActions}</div><small>${romIdentityDetail}</small></td>
        <td class="rom-purpose-cell" data-label="Purpose and entry points"><strong>${romPurpose}</strong><small>${romEntries || esc(entry.filetype || "No decoded entry points")}</small></td>
        <td class="rom-usage-cell" data-label="Contents"><strong>${romUsage}</strong><small>${romMatches}</small><small class="rom-hash" title="SHA-256 ${esc(entry.diagnostics?.sha256 || "Unavailable")}">${entry.diagnostics?.sha256 ? `SHA-256 ${esc(entry.diagnostics.sha256.slice(0, 12))}…` : ""}</small></td>`
      : `<td class="file-name-cell"><div class="file-name-wrap"><span class="file-icon ${visual.kind}" title="${esc(visual.label)}">${icon}</span><strong>${esc(entry.name)}</strong>
        ${downloadAction}${rowActions}
      </div></td>
      <td class="meta">${esc(isVirtual ? "Grouped results" : isDir ? (isArchive ? "Container folder" : "Folder") : isArchiveFile ? "Container" : isArchive ? "Container file" : "File")}</td>
      <td class="meta">${esc(size)}</td>
      <td class="meta datestamp-cell" data-label="Modified">${editableMetadata
        ? `<button type="button" class="metadata-edit" title="Edit the GEMDOS attributes and datestamp">${esc(entry.datestamp || "-")}</button>`
        : esc(entry.datestamp || "-")}</td>
      ${accessCell}`;
    return `<tr class="file-row${selectedKeys.has(entryKey) ? " selected" : ""}${isVirtual ? " virtual-catalogue-row" : ""}${entry.catalogueBreak ? " catalogue-break" : ""}${rowIsPendingCut(pane, entry) ? " clipboard-cut" : ""}"${openHint}
      aria-selected="${selectedKeys.has(entryKey)}"
      tabindex="0" draggable="${!isArchive && !isVirtual && !isPartitionIndex}" data-key="${esc(entryKey)}" data-name="${esc(entry.name)}" data-path="${esc(entry.path || "")}" data-type="${entryType}" data-archive="${isArchiveFile ? "1" : "0"}" data-partition="${entry.partition ?? ""}" data-bank="${entry.bank ?? ""}" data-virtual="${isVirtual ? "1" : "0"}">
      ${cells}
    </tr>`;
  }).join("");
  const matchingFormat = matchingBlankImageFormat(pane);
  const canNewFile = canEdit && !isArchive;
  const newSubmenu = `<details class="menu-submenu"><summary><b>＋</b><span>New</span><small>›</small></summary><div class="menu-submenu-panel">
    <button class="menu-command menu-new-matching-image" data-format="${matchingFormat.value}"><b>▤</b><span>New Image (${esc(matchingFormat.label)})…</span></button>
    ${canNewFile ? '<button class="menu-command new-empty-file"><b>F</b><span>New file…</span></button>' : ""}
    ${canFolder ? '<button class="menu-command new-folder"><b>▢</b><span>New folder…</span></button>' : ""}
  </div></details>`;
  const clipboardSelection = clipboardItemsForPane(index);
  const clipboardTools = `<details class="tool-menu edit-tools">
    <summary class="tool"><b>✎</b><span>Edit</span></summary>
    <div class="tool-menu-panel">
      <button class="menu-command clipboard-cut-action" ${!isArchive && clipboardSelection.length && !pane.image.readOnly && !isContainer ? "" : "disabled"} title="Cut selected items"><b>✂</b><span>Cut <small>Ctrl/Cmd+X</small></span></button>
      <button class="menu-command clipboard-copy-action" ${!isArchive && clipboardSelection.length ? "" : "disabled"} title="Copy selected items"><b>⧉</b><span>Copy <small>Ctrl/Cmd+C</small></span></button>
      <button class="menu-command clipboard-paste-action" ${!isArchive && canPasteIntoPane(pane) ? "" : "disabled"} title="Paste once into this location"><b>▣</b><span>Paste <small>Ctrl/Cmd+V</small></span></button>
      ${pane.image.readOnly || isContainer ? "" : `<span class="menu-separator" role="separator"></span>
        <button class="menu-command undo-image" ${pane.image.checkpoints?.canUndo ? "" : "disabled"}><b>↶</b><span>Undo last change</span></button>
        <button class="menu-command manage-checkpoints"><b>◉</b><span>Checkpoints…</span></button>`}
    </div>
  </details>`;
  const fileTools = `<details class="tool-menu file-tools">
    <summary class="tool"><b>▤</b><span>File</span></summary>
    <div class="tool-menu-panel">
      ${newSubmenu}
      <button class="menu-command menu-load-image"><b>▤</b><span>Open image…</span></button>
      <button class="menu-command menu-save-image"><b>⇩</b><span>Save image</span></button>
      ${pane.image.exportFormats?.length ? `<button class="menu-command menu-export-image"><b>⇄</b><span>Export as…</span></button>` : ""}
      ${isContainer || pane.image.readOnly ? "" : `<span class="menu-separator" role="separator"></span>`}
      ${isPartitionIndex ? ""
        : !isContainer && !pane.image.readOnly ? `<button class="menu-command import-file"><b>＋</b><span>${isRom ? "Insert ROM bank(s)…" : "Insert File…"}</span></button>
          <button class="menu-command import-folder"><b>▣</b><span>Insert Folder &amp; Contents…</span></button>
          ${isRom
            ? `<button class="menu-command append-rom-bank"><b>▥</b><span>Append empty bank</span></button>`
            : ""}` : ""}
      <span class="menu-separator" role="separator"></span>
      <button class="menu-command menu-close-pane"><b>×</b><span>Close pane</span></button>
    </div>
  </details>`;
  const viewTools = `<details class="tool-menu view-tools">
    <summary class="tool"><b>◫</b><span>View</span></summary>
    <div class="tool-menu-panel">
      <button class="menu-command view-refresh"><b>↻</b><span>Refresh current view</span></button>
      ${pane.partition !== null ? '<button class="menu-command view-partitions"><b>▦</b><span>Return to the partition table</span></button>' : ""}
    </div>
  </details>`;
  const onlineLibraryAction = isArchive || isContainer || isRom || pane.image.readOnly ? "" :
    `<button class="menu-command online-library" ><b>⌕</b><span>Find software online…</span></button>`;
  const libraryTools = `<details class="tool-menu library-tools">
    <summary class="tool"><b>⌕</b><span>Library</span></summary>
    <div class="tool-menu-panel">
      ${onlineLibraryAction}
      <button class="menu-command collection-catalogue"><b>▦</b><span>Private collection…</span></button>
    </div>
  </details>`;
  const analysisTools = `<details class="tool-menu">
    <summary class="tool"><b>⌁</b><span>Analyse</span></summary>
    <div class="tool-menu-panel tool-menu-panel-right">
      <button class="menu-command health-dashboard"><b>♥</b><span>Image health dashboard</span></button>
      ${isRom || isArchive ? "" : '<button class="menu-command preflight-selection"><b>◫</b><span>Dry-run selected items</span></button>'}
      ${!isArchive && !isRom && !isPartitionIndex ? `<button class="menu-command inspect-file" ${selected && selected.type !== "dir" && selected.type !== "directory" ? "" : "disabled"}><b>⌕</b><span>Open selected file</span></button><button class="menu-command inspect-dependencies" ${selected && selected.type !== "dir" && selected.type !== "directory" ? "" : "disabled"}><b>⛓</b><span>Check loader dependencies</span></button>` : ""}
      <button class="menu-command find-duplicates"><b>≡</b><span>${isPartitionIndex ? "Check for duplicate games" : "Find duplicates / variants"}</span></button>
      <button class="menu-command compare-image" ${panes.some((other, otherIndex) => otherIndex !== index && other.image?.id && other.image.id !== pane.image.id) ? "" : 'disabled title="Open another image to compare."'}><b>⇄</b><span>Compare with open image…</span></button>
      <button class="menu-command apply-image-patch" ${pane.image.readOnly || isContainer ? "disabled" : ""}><b>⇥</b><span>Apply guarded patch…</span></button>
      <button class="menu-command export-manifest"><b>⇩</b><span>Export collection manifest</span></button>
    </div>
  </details>`;
  const emulatorMediaApplicable = !isArchive && !isRom && !isTosRom;
  const emulatorTargetName = isDrive
    ? "hard drive"
    : isContainer ? "floppy container" : "image";
  const emulatorActions = emulatorMediaApplicable
    ? `<span class="menu-separator" role="separator"></span>
        <button class="menu-command run-pane-emulator"><b>▶</b><span>Run ${emulatorTargetName}…</span></button>
        <button class="menu-command debug-pane-emulator"><b>⌁</b><span>Debug ${emulatorTargetName}…</span></button>`
    : "";
  // A hard drive cannot be written to a floppy drive, so only the floppy
  // containers offer a physical write.
  const physicalSuffix = String(pane.image.name || "").toLowerCase().match(/\.(st|msa|dim|stx|hfe|scp|ipf)$/);
  const physicalMediaApplicable = !isDrive && !isHardDiskVolume && Boolean(physicalSuffix);
  const physicalHostAvailable = hasHostCapability("physical-floppy-write");
  const physicalFloppyAction = physicalMediaApplicable
    ? `<span class="menu-separator" role="separator"></span><button class="menu-command write-physical-floppy" ${physicalHostAvailable ? "" : 'disabled title="Physical drives are available in the native Linux host."'}><b>▣</b><span>Write physical floppy…</span></button>`
    : "";
  const utilityTools = `<details class="tool-menu">
    <summary class="tool"><b>⋯</b><span>Tools</span></summary>
    <div class="tool-menu-panel tool-menu-panel-right">
      <button class="menu-command open-hex-editor"><b>0x</b><span>Hex editor…</span></button>
      ${emulatorActions}
      ${physicalFloppyAction}
      <button class="menu-command build-deployment"><b>⇩</b><span>Build hardware deployment…</span></button>
      ${isPartitionIndex ? "" : `<button class="menu-command validate-image"><b>✓</b><span>${isRom ? "Check ROM structure" : "Check filesystem"}</span></button>`}
      ${(isHardDiskVolume || acceptsInstall) && DRIVE_SOFTWARE_AUDIT_AVAILABLE ? '<button class="menu-command audit-drive-software"><b>⌁</b><span>Check installed drive software…</span></button>' : ""}
      ${acceptsInstall ? `<span class="menu-separator" role="separator"></span>
        <button class="menu-command prepare-drive"><b>⌘</b><span>Prepare this drive…</span></button>
        <button class="menu-command run-title-installer"><b>◎</b><span>Run a title's own installer…</span></button>
        <button class="menu-command staged-installations"><b>▤</b><span>Staged disks…</span></button>`
        : '<button class="menu-command staged-installations"><b>▤</b><span>Staged disks…</span></button>'}
      ${isArchive ? "" : isRom ? '<button class="menu-command rom-workbench"><b>⌬</b><span>ROM Workbench…</span></button><button class="menu-command configure-rom"><b>▥</b><span>ROM layout…</span></button>' : isTosRom ? "" : isPartitionIndex || isContainer ? (isContainer ? '<button class="menu-command container-project"><b>≋</b><span>Container project…</span></button><button class="menu-command convert-container"><b>⇥</b><span>Convert container…</span></button>' : "") : pane.image.readOnly ? "" : '<button class="menu-command compact-image"><b>≋</b><span>Compact filesystem</span></button>'}
    </div>
  </details>`;
  const exportControl = exportAvailability(pane.image);

  const toolbarMarkup = `${fileTools}${clipboardTools}${viewTools}${libraryTools}

      ${analysisTools}
      ${utilityTools}

      <span class="tool-spacer"></span>`;

  host.className = `pane${pane.image.dirty ? " dirty" : ""}`;
  host.innerHTML = `
    <header class="pane-head">
      ${paneDragHandle(index)}
      <span class="format-icon ${kind}">${paneFormat(pane.image)}</span>
      <div class="image-name"><button class="image-title" type="button" title="Rename ${esc(pane.image.name)}">${esc(pane.image.name)}</button><small>${esc(location)} · ${humanSize(pane.image.size)}</small></div>
      <span class="dirty-dot" role="img" aria-label="Changes made" title="Changes made · save before closing"></span>
      <div class="pane-head-actions" aria-label="Image actions">
        <button class="icon-button new-image" title="New Blank Image" aria-label="New Blank Image">${PANE_ICONS.newImage}</button>
        <button class="icon-button replace-image" title="Load New Image" aria-label="Load New Image">${PANE_ICONS.loadImage}</button>
        <button class="icon-button save-image" title="Save Image" aria-label="Save Image">${PANE_ICONS.saveImage}</button>
        <button class="icon-button export-image" title="${esc(exportControl.label)}" aria-label="${esc(exportControl.label)}"${exportControl.available ? "" : " disabled"}>${PANE_ICONS.exportImage}</button>
        <button class="icon-button refresh-image" title="Refresh View" aria-label="Refresh View">${PANE_ICONS.refreshView}</button>
        <button class="icon-button minimize-pane" title="Minimise Pane" aria-label="Minimise Pane">${PANE_ICONS.minimizePane}</button>
        <button class="icon-button maximize-pane" title="Maximise Pane" aria-label="Maximise Pane" aria-pressed="false">${PANE_ICONS.maximizePane}</button>
        <button class="icon-button close-image" title="Close Pane" aria-label="Close Pane">${PANE_ICONS.closePane}</button>
      </div>
    </header>
    <nav class="toolbar" aria-label="Pane menus">
      ${toolbarMarkup}
    </nav>
    <div class="breadcrumbs">${isArchive ? archiveCrumbs(pane) : isPartitionIndex ? '<span class="crumb current">All drives</span>' : isRom ? '<span class="crumb current">ROM bank inventory</span>' : pane.partition !== null ? `<button class="crumb drive-home">All drives</button><span>›</span>${crumbs(pane.path, false, driveLetter)}` : crumbs(pane.path, false, driveLetter)}</div>
    ${isRom ? `<aside class="rom-pane-guide" aria-label="ROM pane guidance"><span><b>ⓘ Info</b> decodes headers, commands, strings and modules</span><span><b>Double-click</b> opens the bank in Hex</span><span><b>Tools → ROM Workbench</b> analyses code, revisions and hardware</span><span><b>ROM layout</b> changes bank interpretation without rewriting bytes</span></aside>` : ""}
    ${isTosRom ? `<aside class="rom-pane-guide" aria-label="TOS ROM pane guidance"><span><b>Read-only segments</b> · the operating system as TOS lays it out in ROM</span><span><b>Double-click</b> opens a segment in Hex</span><span><b>Check ROM structure</b> verifies the header and its checksum</span><span><b>A TOS ROM is never written</b> · export the bytes to change them elsewhere</span></aside>` : ""}
    <div class="list-wrap">
      ${loadingMarkup(pane)}
      ${(parentRow || rows) ? `<table class="file-list${isPartitionIndex ? " partition-list" : ""}${isRom ? " rom-bank-list" : " catalogue-file-list"}" role="grid" aria-label="${isPartitionIndex ? "Hard drive partitions" : isRom ? "ROM bank inventory" : "Files in " + esc(location)}"><thead><tr>${isPartitionIndex ? "<th>Drive</th><th>Identifier</th><th>Size</th><th>Filing system</th><th>Boot</th>" : isRom ? "<th>Bank and address</th><th>Identity</th><th>Purpose and entry points</th><th>Contents</th>" : '<th>Name</th><th>Kind</th><th>Size</th><th title="Datestamp of the last change">Modified</th><th title="GEMDOS attribute byte">Attributes</th>'}</tr></thead><tbody>${parentRow}${rows}</tbody></table>` : '<div class="empty-list">Nothing here yet.<br>Drop a host file into this pane to add it.</div>'}
    </div>
    <footer class="pane-foot"><span>${pane.image.readOnly ? "Read-only safe view · " : ""}${selectedKeys.size ? `${selectedKeys.size} selected · ` : ""}${pane.entries.length} ${isPartitionIndex ? `partition${pane.entries.length === 1 ? "" : "s"}` : isRom ? `bank${pane.entries.length === 1 ? "" : "s"}` : "objects"} · ${esc(pane.description || "")}</span>${capacityMarkup(pane.capacity)}</footer>`;

  fitPaneMenus(host);

  if (pane.loading || pane.actionPending) {
    host.querySelectorAll("button").forEach(button => {
      button.disabled = true;
    });
  }
  host.querySelector(".replace-image").onclick = () => chooseImage(index);
  host.querySelector(".new-image").onclick = () => guardedPaneAction(index, () => showCreateImageModal(index));
  const imageTitle = host.querySelector(".image-title");
  imageTitle.onclick = () => beginImageRename(index);
  if (physicalMediaApplicable) {
    imageTitle.oncontextmenu = event => showPhysicalFloppyContextMenu(index, event, physicalHostAvailable);
    host.querySelector(".format-icon").oncontextmenu = event => showPhysicalFloppyContextMenu(index, event, physicalHostAvailable);
  }
  host.querySelector(".refresh-image").onclick = () => refreshCurrentView(index);
  host.querySelector(".menu-new-matching-image")?.addEventListener("click", event => guardedPaneAction(index, () => newImageFromFileMenu(index, event.currentTarget.dataset.format)));
  host.querySelector(".menu-load-image")?.addEventListener("click", () => chooseImage(index));
  host.querySelector(".menu-save-image")?.addEventListener("click", () => guardedPaneAction(index, () => saveImage(index)));
  host.querySelector(".menu-export-image")?.addEventListener("click", () => guardedPaneAction(index, () => exportImageAs(index)));
  host.querySelector(".export-image")?.addEventListener("click", () => guardedPaneAction(index, () => exportImageAs(index)));
  host.querySelector(".menu-close-pane")?.addEventListener("click", () => closePane(index));
  host.querySelector(".view-refresh")?.addEventListener("click", () => refreshCurrentView(index));
  host.querySelector(".view-partitions")?.addEventListener("click", () => returnToPartitions(index));
  host.querySelector(".clipboard-cut-action")?.addEventListener("click", () => setWorkspaceClipboard(index, "cut"));
  host.querySelector(".clipboard-copy-action")?.addEventListener("click", () => setWorkspaceClipboard(index, "copy"));
  host.querySelector(".clipboard-paste-action")?.addEventListener("click", () => pasteWorkspaceClipboard(index));
  host.querySelector(".close-image").onclick = () => closePane(index);
  host.querySelector(".drive-home")?.addEventListener("click", () => returnToPartitions(index));
  host.querySelector(".archive-exit")?.addEventListener("click", () => leaveArchive(index));
  host.querySelector(".import-file")?.addEventListener("click", () => guardedPaneAction(index, () => chooseHostFile(index)));
  host.querySelector(".import-folder")?.addEventListener("click", () => guardedPaneAction(index, () => chooseHostFolder(index)));
  host.querySelector(".new-folder")?.addEventListener("click", () => guardedPaneAction(index, () => createFolder(index)));
  host.querySelector(".new-empty-file")?.addEventListener("click", () => guardedPaneAction(index, () => createEmptyFile(index)));
  host.querySelector(".append-rom-bank")?.addEventListener("click", () => guardedPaneAction(index, () => appendBlankRomBank(index)));
  host.querySelector(".configure-rom")?.addEventListener("click", () => guardedPaneAction(index, () => configureRomLayout(index)));
  host.querySelector(".rom-workbench")?.addEventListener("click", () => guardedPaneAction(index, () => showRomWorkbench(index)));
  host.querySelector(".online-library")?.addEventListener("click", () => guardedPaneAction(index, () => showOnlineLibrary(index)));
  host.querySelector(".collection-catalogue")?.addEventListener("click", () => showCollectionCatalogue(index));
  host.querySelector(".validate-image")?.addEventListener("click", () => guardedPaneAction(index, () => validateImage(index)));
  host.querySelector(".audit-drive-software")?.addEventListener("click", () => guardedPaneAction(index, () => showDriveSoftwareAudit(index)));
  host.querySelector(".staged-installations")?.addEventListener("click", () => guardedPaneAction(index, () => showStagedInstallations(index)));
  host.querySelector(".prepare-drive")?.addEventListener("click", () => guardedPaneAction(index, () => showPrepareDrive(index)));
  host.querySelector(".run-title-installer")?.addEventListener("click", () => guardedPaneAction(index, () => showTitleInstaller(index)));
  host.querySelector(".open-hex-editor")?.addEventListener("click", () => guardedPaneAction(index, () => openHexEditor(index)));
  host.querySelector(".run-pane-emulator")?.addEventListener("click", () => guardedPaneAction(index, () => launchPaneEmulator(index, false)));
  host.querySelector(".debug-pane-emulator")?.addEventListener("click", () => guardedPaneAction(index, () => launchPaneEmulator(index, true)));
  host.querySelector(".write-physical-floppy")?.addEventListener("click", () => guardedPaneAction(index, () => showPhysicalFloppyDialog(index)));
  host.querySelector(".convert-container")?.addEventListener("click", () => guardedPaneAction(index, () => convertContainer(index)));
  host.querySelector(".container-project")?.addEventListener("click", () => guardedPaneAction(index, () => showContainerProject(index)));
  host.querySelector(".compact-image")?.addEventListener("click", () => guardedPaneAction(index, () => compactImage(index)));
  host.querySelector(".undo-image")?.addEventListener("click", () => guardedPaneAction(index, () => undoLastChange(index)));
  host.querySelector(".manage-checkpoints")?.addEventListener("click", () => guardedPaneAction(index, () => showCheckpointManager(index)));
  host.querySelector(".health-dashboard")?.addEventListener("click", () => guardedPaneAction(index, () => showHealthDashboard(index)));
  host.querySelector(".preflight-selection")?.addEventListener("click", () => guardedPaneAction(index, () => showSelectionPreflight(index)));
  host.querySelector(".build-deployment")?.addEventListener("click", () => guardedPaneAction(index, () => showDeploymentAssistant(index)));
  host.querySelector(".inspect-file")?.addEventListener("click", () => guardedPaneAction(index, () => showFileInspector(index)));
  host.querySelector(".inspect-dependencies")?.addEventListener("click", () => guardedPaneAction(index, () => showDependencyReport(index)));
  host.querySelector(".find-duplicates")?.addEventListener("click", () => guardedPaneAction(index, () => showDuplicateReport(index)));
  host.querySelector(".export-manifest")?.addEventListener("click", () => showManifestExport(index));
  host.querySelector(".compare-image")?.addEventListener("click", () => showImageComparison(index));
  host.querySelector(".apply-image-patch")?.addEventListener("click", () => showApplyImagePatch(index));
  host.querySelector(".save-image").onclick = () => guardedPaneAction(index, () => saveImage(index));
  host.querySelectorAll(".tool-menu").forEach(menu => {
    menu.addEventListener("toggle", () => {
      if (!menu.open) return;
      host.querySelectorAll(".tool-menu[open]").forEach(other => {
        if (other !== menu) other.removeAttribute("open");
      });
    });
    menu.querySelectorAll(".menu-command").forEach(command => {
      command.addEventListener("click", () => menu.removeAttribute("open"));
    });
  });
  host.querySelectorAll(".crumb[data-path]").forEach(button => button.onclick = () => navigate(index, button.dataset.path));
  host.querySelectorAll(".crumb[data-archive-member]").forEach(button => button.onclick = () => navigateArchive(index, button.dataset.archiveMember));
  host.querySelectorAll(".file-row").forEach(row => wireRow(row, index));
  if (isGemdos) {
    const diskHandle = host.querySelector(".format-icon");
    diskHandle.draggable = true;
    diskHandle.classList.add("disk-transfer-handle");
    diskHandle.title = "Drag this disk image into another pane";
    diskHandle.setAttribute("aria-label", `${paneFormat(pane.image)} disk image. Drag to transfer it to another pane.`);
    diskHandle.ondragstart = event => {
      event.dataTransfer.effectAllowed = "copy";
      event.dataTransfer.setData("application/x-atari-disk", JSON.stringify({
        image: pane.image.id, partition: pane.partition, name: pane.partitionName || pane.image.name
      }));
    };
  }
  wireDropZone(host, index);
  paneWindowManager.mount(index, host);
  const listWrap = host.querySelector(".list-wrap");
  if (preserveScroll) listWrap.scrollTop = previousScrollTop;
  if (isPartitionIndex) {
    if (!preserveScroll && pane.driveScrollTop) listWrap.scrollTop = pane.driveScrollTop;
    listWrap.addEventListener("scroll", () => {
      pane.driveScrollTop = listWrap.scrollTop;
    }, { passive: true });
  }
  refreshImageComparisonActions();
  rememberOpenPanes();
}

function refreshImageComparisonActions() {
  panes.forEach((pane, index) => {
    const button = document.querySelector(`.pane[data-pane="${index}"] .compare-image`);
    if (!button || !pane.image) return;
    const available = panes.some((other, otherIndex) =>
      otherIndex !== index && other.image?.id && other.image.id !== pane.image.id
    );
    button.disabled = !available;
    button.title = available ? "" : "Open another image to compare.";
  });
}

function wireRow(row, index) {
  if (row.dataset.parent === "1") {
    row.ondblclick = event => {
      event.stopPropagation();
      openEntry(index, row);
    };
    row.onkeydown = event => {
      if (event.key === "Enter") openEntry(index, row);
    };
    return;
  }
  if (row.dataset.virtual === "1") {
    row.ondblclick = event => {
      event.stopPropagation();
      openEntry(index, row);
    };
    row.onkeydown = event => {
      if (event.key === "Enter") openEntry(index, row);
    };
    row.ondragover = event => {
      const hasInternalFiles = event.dataTransfer.types.includes("application/x-atari-files");
      if (!hasInternalFiles && !event.dataTransfer.types.includes("Files")) return;
      event.preventDefault();
      event.stopPropagation();
      row.classList.add("folder-drop-target");
    };
    row.ondragleave = () => row.classList.remove("folder-drop-target");
    row.ondrop = async event => {
      event.preventDefault();
      event.stopPropagation();
      row.classList.remove("folder-drop-target");
      const destination = row.dataset.name;
      const encoded = event.dataTransfer.getData("application/x-atari-files");
      if (encoded) return transferFiles(index, JSON.parse(encoded), destination);
      const dropped = await collectDroppedHostFiles(event.dataTransfer);
      const files = dropped.map(item => item.file);
      if (!files.length) return;
      await navigate(index, destination);
      if (dropped.some(item => item.relativePath.includes("/"))) await addSelectedHostFolder(index, dropped);
      else await addSelectedHostFiles(index, files);
    };
    return;
  }
  const selectForAction = preserveSelectedGroup => {
    const pane = panes[index];
    if (
      preserveSelectedGroup
      && selectionKeys(pane).length > 1
      && selectionKeys(pane).includes(row.dataset.key)
    ) return;
    setSelection(panes[index], [row.dataset.key], row.dataset.key);
    refreshSelectionDisplay(index);
  };
  row.querySelector(".row-rom-inspect")?.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    selectForAction(false);
    showRomStructure(index, Number(row.dataset.bank)).catch(error => {
      toast(`Could not decode that ROM bank: ${error.message}`, true);
    });
  });
  row.querySelector(".row-download")?.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    if (panes[index].archivePath) window.location.href = archiveMemberUrl(panes[index], row.dataset.name);
    else downloadFile(index, row.dataset.name, row.dataset.path || null);
  });
  row.querySelectorAll(".metadata-edit").forEach(button => button.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    selectForAction(false);
    editFileMetadata(index, selectedEntry(index)).catch(error => {
      toast(`Could not change the attributes: ${error.message}`, true);
    });
  }));
  row.querySelector(".row-rename")?.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    selectForAction(false);
    guardedPaneAction(index, () => renameSelected(index));
  });
  row.querySelector(".row-delete")?.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    selectForAction(true);
    guardedPaneAction(index, () => deleteSelected(index));
  });
  row.querySelector(".row-read-write")?.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    selectForAction(true);
    guardedPaneAction(index, () => setSelectedAccess(index, true));
  });
  row.querySelector(".row-read-only")?.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    selectForAction(true);
    guardedPaneAction(index, () => setSelectedAccess(index, false));
  });
  row.onclick = event => {
    event.stopPropagation();
    if (event.detail !== 1) return;
    const toggle = event.ctrlKey || event.metaKey;
    const range = event.shiftKey;
    selectRow(index, row.dataset.key, { toggle, range });
    refreshSelectionDisplay(index);
  };
  row.ondblclick = event => {
    event.stopPropagation();
    openEntry(index, row);
  };
  row.onkeydown = event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      event.preventDefault();
      const keys = panes[index].entries
        .filter(entry => entry.type !== "partition")
        .map(entrySelectionKey);
      setSelection(panes[index], keys, row.dataset.key);
      refreshSelectionDisplay(index);
      return;
    }
    if (event.key === "Enter") openEntry(index, row);
    if (event.key === "Delete") deleteSelected(index);
  };
  row.ondragstart = event => {
    const pane = panes[index];
    if (row.dataset.type === "partition") return event.preventDefault();
    if (!selectionKeys(pane).includes(row.dataset.key)) {
      setSelection(pane, [row.dataset.key], row.dataset.key);
      document.querySelectorAll(`.pane[data-pane="${index}"] .file-row`).forEach(item => {
        const selected = item === row;
        item.classList.toggle("selected", selected);
        item.setAttribute("aria-selected", String(selected));
      });
    }
    const sources = selectedEntries(index)
      .filter(entry => entry.type !== "partition")
      .map(entry => ({
        pane: index,
        image: pane.image.id,
        partition: pane.partition,
        side: pane.side,
        path: pane.image.kind === "rom" ? `bank:${entry.bank}` : entryImagePath(pane, entry),
        name: pane.image.kind === "rom" ? `BANK${String(entry.bank).padStart(3, "0")}` : entry.name,
        length: Number(entry.length || 0),
        romBank: pane.image.kind === "rom" ? Number(entry.bank) : undefined,
        recursive: entry.type === "dir" || entry.type === "directory"
      }));
    document.querySelectorAll(`.pane[data-pane="${index}"] .file-row.selected`).forEach(item => {
      item.classList.add("dragging");
    });
    event.dataTransfer.effectAllowed = "copyMove";
    event.dataTransfer.setData("application/x-atari-files", JSON.stringify(sources));
    event.dataTransfer.setData("application/x-atari-file", JSON.stringify(sources[0]));
    event.dataTransfer.setData("text/plain", sources.length === 1 ? sources[0].name : `${sources.length} Atari files`);
  };
  if (panes[index].image.kind === "rom") {
    row.ondragover = event => {
      if (!event.dataTransfer.types.includes("application/x-atari-files") && !event.dataTransfer.types.includes("Files")) return;
      event.preventDefault();
      event.stopPropagation();
      row.classList.add("folder-drop-target");
    };
    row.ondragleave = () => row.classList.remove("folder-drop-target");
    row.ondrop = async event => {
      event.preventDefault();
      event.stopPropagation();
      row.classList.remove("folder-drop-target");
      const encoded = event.dataTransfer.getData("application/x-atari-files");
      if (encoded) return transferFiles(index, JSON.parse(encoded), `bank:${row.dataset.bank}`);
      const dropped = await collectDroppedHostFiles(event.dataTransfer);
      const files = dropped.map(item => item.file);
      if (files.length) return addRomHostFiles(index, files, Number(row.dataset.bank));
    };
  } else if (
    paneHoldsVolume(panes[index])
    && row.dataset.type === "dir"
  ) {
    row.ondragover = event => {
      if (!event.dataTransfer.types.includes("application/x-atari-files")) return;
      event.preventDefault();
      event.stopPropagation();
      row.classList.add("folder-drop-target");
    };
    row.ondragleave = event => {
      if (!row.contains(event.relatedTarget)) {
        row.classList.remove("folder-drop-target");
      }
    };
    row.ondrop = event => {
      const encoded = event.dataTransfer.getData("application/x-atari-files");
      if (!encoded) return;
      event.preventDefault();
      event.stopPropagation();
      row.classList.remove("folder-drop-target");
      transferFiles(
        index,
        JSON.parse(encoded),
        fullPath(panes[index].path, row.dataset.name),
      );
    };
  }
  row.ondragend = () => {
    document.querySelectorAll(`.pane[data-pane="${index}"] .file-row.dragging`).forEach(item => {
      item.classList.remove("dragging");
    });
  };
}

function refreshSelectionDisplay(index) {
  const pane = panes[index];
  const host = document.querySelector(`.pane[data-pane="${index}"]`);
  const selectedKeys = new Set(selectionKeys(pane));
  const selected = selectedEntry(index);
  const isPartitionIndex = pane.image?.kind === "hd" && pane.partition === null;

  host.querySelectorAll(".file-row").forEach(row => {
    const isSelected = selectedKeys.has(row.dataset.key);
    row.classList.toggle("selected", isSelected);
    row.setAttribute("aria-selected", String(isSelected));
    const multiSelection = selectedKeys.size > 1;
    const rename = row.querySelector(".row-rename");
    const remove = row.querySelector(".row-delete");
    const accessActions = row.querySelector(".access-actions");
    if (rename) rename.hidden = multiSelection;
    if (remove) remove.hidden = multiSelection && !isSelected;
    if (accessActions) accessActions.hidden = multiSelection && !isSelected;
  });
  const disable = (selector, disabled) => {
    const control = host.querySelector(selector);
    if (control) control.disabled = disabled;
  };
  const hasInspectableSelection = Boolean(selected && selected.type !== "dir" && selected.type !== "directory");
  disable(".inspect-file", !hasInspectableSelection);
  disable(".inspect-dependencies", !hasInspectableSelection);
  const clipboardSelection = clipboardItemsForPane(index);
  disable(".clipboard-cut-action", !clipboardSelection.length || pane.image.readOnly || READ_ONLY_KINDS.includes(pane.image.kind));
  disable(".clipboard-copy-action", !clipboardSelection.length);
  disable(".clipboard-paste-action", !canPasteIntoPane(pane));

  const footer = host.querySelector(".pane-foot > span:first-child");
  if (footer) {
    footer.textContent =
      `${selectedKeys.size ? `${selectedKeys.size} selected · ` : ""}`
      + `${pane.entries.length} ${isPartitionIndex ? "partitions" : "objects"}`
      + ` · ${pane.description || ""}`;
  }
}

function wireDropZone(host, index) {
  host.ondragover = event => {
    event.preventDefault();
    host.classList.add("drag-target");
    event.dataTransfer.dropEffect = "copy";
  };
  host.ondragleave = event => {
    if (!host.contains(event.relatedTarget)) host.classList.remove("drag-target");
  };
  host.ondrop = async event => {
    event.preventDefault();
    host.classList.remove("drag-target");
    if (panes[index].loading || panes[index].actionPending) {
      return toast("Wait for the current operation to finish.", true);
    }
    const openDisk = event.dataTransfer.getData("application/x-atari-disk");
    const diskSource = openDisk ? JSON.parse(openDisk) : null;
    if (diskSource && paneHoldsVolume(panes[index])) {
      if (diskSource.image === panes[index].image.id) {
        return toast("Choose a different volume as the destination.", true);
      }
      return copyDiskImageToVolume(index, diskSource);
    }
    const internalBatch = event.dataTransfer.getData("application/x-atari-files");
    if (internalBatch) return transferFiles(index, JSON.parse(internalBatch));
    const internal = event.dataTransfer.getData("application/x-atari-file");
    if (internal) return transferFiles(index, [JSON.parse(internal)]);
    const dropped = await collectDroppedHostFiles(event.dataTransfer);
    const files = dropped.map(item => item.file);
    if (!files.length) return;
    if (dropped.some(item => item.relativePath.includes("/")) && panes[index].image) {
      return addSelectedHostFolder(index, dropped);
    }
    const images = files.filter(file => formats.isImportableImage(file.name));
    if (!panes[index].image) return openFiles(index, files);
    if (images.length && paneHoldsVolume(panes[index])) {
      for (const file of files) await importHostFile(index, file);
      return;
    }
    if (images.length) return openFiles(index, files);
    for (const file of files) await importHostFile(index, file);
  };
}

async function copyDiskImageToVolume(index, source) {
  const target = panes[index];
  const rule = targetNameRule(target, formats.stem(source.name));
  const preview = await paneOperation(
    index,
    `Reading ${source.name} contents…`,
    () => api(`/api/images/${source.image}/preview`)
  );
  return showImageExtractionPlan(index, {
    heading: `Copy ${source.name} onto this volume`,
    sourceName: source.name,
    preview,
    suggestedName: rule.suggested,
    allowRaw: false,
    allowInstall: paneAcceptsInstall(target),
    submitLabel: "Copy image contents",
    onExtract: plan => performDiskImageToVolumeCopy(index, source, plan),
    onInstall: plan => performInstall(index, source.image, source.name, plan),
  });
}

async function performDiskImageToVolumeCopy(index, source, plan) {
  const target = panes[index];
  const destinationLabel = plan.createDirectory ? plan.directoryName : plan.targetPath;
  const data = await trackedPaneOperation(index, `Copying ${source.name} into ${destinationLabel}…`, operationId =>
    api("/api/transfer-image-to-directory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sourceImage: source.image,
        targetImage: target.image.id,
        targetPath: plan.targetPath,
        directoryName: plan.directoryName,
        createDirectory: plan.createDirectory,
        operationId
      })
    }));
  target.image = data.image;
  await loadDirectory(index);
  toast(`${source.name} contents copied into ${data.path}`);
}

async function openEntry(index, row) {
  const pane = panes[index];
  if (row.dataset.parent === "1") {
    if (pane.archivePath) {
      if (pane.archiveMember) await navigateArchive(index, pane.archiveMember.split("/").slice(0, -1).join("/"));
      else await leaveArchive(index);
    } else if (pane.partition !== null && pane.path === "") await returnToPartitions(index);
    else await navigate(index, parentPath(pane.path));
  } else if (row.dataset.type === "rom-bank") {
    await openHexEditor(index, Number(row.dataset.bank) * (pane.image.rom?.bankSize || 16384));
  } else if (row.dataset.type === "partition") {
    const entry = pane.entries.find(item => item.partition === Number(row.dataset.partition));
    pane.partition = Number(row.dataset.partition);
    pane.partitionName = entry?.name || "";
    pane.path = "";
    await loadDirectory(index);
  } else if (row.dataset.archive === "1") {
    await enterArchive(index, row.dataset.name);
  } else if (row.dataset.type === "dir") {
    if (pane.archivePath) await navigateArchive(index, [pane.archiveMember, row.dataset.name].filter(Boolean).join("/"));
    else await navigate(index, row.dataset.path || fullPath(pane.path, row.dataset.name));
  } else if (pane.archivePath) {
    await openFileEditor(index, row.dataset.name, archiveMemberTarget(pane, row.dataset.name));
  } else {
    await openFileEditor(index, row.dataset.name, null, row.dataset.path || null);
  }
}

async function enterArchive(index, name) {
  const pane = panes[index];
  pane.archivePath = fullPath(pane.path, name);
  pane.archiveName = name;
  pane.archiveMember = "";
  pane.archiveKind = "";
  await loadDirectory(index);
}

async function navigateArchive(index, member) {
  panes[index].archiveMember = String(member || "");
  await loadDirectory(index);
}

async function leaveArchive(index) {
  const pane = panes[index];
  pane.archivePath = null;
  pane.archiveName = "";
  pane.archiveMember = "";
  pane.archiveKind = "";
  await loadDirectory(index);
}

function archiveMemberUrl(pane, name, bundleMetadata = true) {
  const query = new URLSearchParams({
    path: pane.archivePath,
    name: pane.archiveName,
    member: [pane.archiveMember, name].filter(Boolean).join("/"),
  });
  if (pane.partition !== null) query.set("partition", pane.partition);
  if (pane.side !== null) query.set("side", pane.side);
  if (bundleMetadata) query.set("bundle", "metadata");
  return `/api/images/${pane.image.id}/archive/file?${query}`;
}

function archiveMemberTarget(pane, name) {
  const member = [pane.archiveMember, name].filter(Boolean).join("/");
  const context = {
    path: pane.archivePath,
    name: pane.archiveName,
    member,
    ...(pane.partition != null ? { partition: pane.partition } : {}),
    ...(pane.side != null ? { side: pane.side } : {}),
  };
  const rawDownloadUrl = `/api/images/${pane.image.id}/archive/file?${new URLSearchParams(context)}`;
  const metadataContext = { ...context, bundle: "metadata" };
  return {
    context,
    displayPath: `${pane.archiveName}/${member}`,
    inspectEndpoint: `/api/images/${pane.image.id}/archive/inspect`,
    disassemblyEndpoint: `/api/images/${pane.image.id}/archive/disassembly`,
    cheatEndpoint: `/api/images/${pane.image.id}/cheat-candidates`,
    hexEndpoint: `/api/images/${pane.image.id}/archive-hex`,
    downloadUrl: `/api/images/${pane.image.id}/archive/file?${new URLSearchParams(metadataContext)}`,
    exportUrl: rawDownloadUrl,
    readOnly: true,
  };
}

async function returnToPartitions(index) {
  const pane = panes[index];
  const previous = pane.partition;
  const requestToken = (pane.requestToken || 0) + 1;
  pane.requestToken = requestToken;
  pane.partition = null;
  pane.partitionName = "";
  pane.path = "";
  setSelection(pane, [String(previous)], String(previous));
  pane.loading = true;
  renderPane(index);
  try {
    const data = await api(`/api/images/${pane.image.id}/partitions`);
    if (panes[index] !== pane || pane.requestToken !== requestToken || pane.partition !== null) return;
    pane.entries = data.partitions;
    pane.capacity = await fetchCapacity(pane.image.id);
    pane.partitionTable = await fetchPartitionTable(pane.image.id);
    pane.description = paneTableDescription(pane);
  } catch (error) {
    if (panes[index] === pane && pane.requestToken === requestToken) toast(error.message, true);
  } finally {
    if (panes[index] !== pane || pane.requestToken !== requestToken || pane.partition !== null) return;
    pane.loading = false;
    renderPane(index);
    document.querySelector(`.pane[data-pane="${index}"] .file-row.selected`)?.scrollIntoView({ block: "center" });
  }
}

async function refreshCurrentView(index) {
  const pane = panes[index];
  if (!pane.image) return;
  if (pane.image.kind === "hd" && pane.partition === null) {
    const selected = selectionKeys(pane);
    const selectionAnchor = pane.selectionAnchor;
    const requestToken = (pane.requestToken || 0) + 1;
    pane.requestToken = requestToken;
    pane.loading = true;
    pane.loadingMessage = "Refreshing the partition table…";
    renderPane(index);
    try {
      const data = await api(`/api/images/${pane.image.id}/partitions`);
      if (panes[index] !== pane || pane.requestToken !== requestToken) return;
      pane.entries = data.partitions;
      pane.capacity = await fetchCapacity(pane.image.id);
      pane.partitionTable = await fetchPartitionTable(pane.image.id);
      setSelection(pane, selected, selectionAnchor);
      pane.description = paneTableDescription(pane);
      toast("Partition table refreshed");
    } catch (error) {
      if (panes[index] === pane && pane.requestToken === requestToken) toast(error.message, true);
    } finally {
      if (panes[index] !== pane || pane.requestToken !== requestToken) return;
      pane.loading = false;
      renderPane(index);
    }
    return;
  }
  pane.loadingMessage = "Refreshing current directory…";
  await loadDirectory(index, true);
  toast("Current view refreshed");
}

async function reloadImageAfterRestore(image) {
  const affected = panes
    .map((pane, index) => pane.image?.id === image.id ? index : -1)
    .filter(index => index >= 0);
  for (const index of affected) {
    await acceptImage(index, image);
  }
  rememberOpenPanes();
}

function undoLastChange(index) {
  const pane = panes[index];
  if (!pane.image?.checkpoints?.canUndo) {
    return toast("There is no change to undo yet.", true);
  }
  showModal(`
    <h2>Undo the last change?</h2>
    <p>The image will return to its state immediately before the most recent image-changing operation.</p>
    <div class="help-note"><strong>Named checkpoints are kept.</strong> Undo consumes only the latest automatic restore point. Any other pane showing this image will refresh too.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="undo">Undo last change</button></div>`,
  async () => {
    const data = await api(`/api/images/${pane.image.id}/undo`, { method: "POST" });
    await reloadImageAfterRestore(data.image);
    toast(`Undone: ${data.checkpoint.reason}`);
  });
}

async function showCheckpointManager(index) {
  const pane = panes[index];
  const data = await api(`/api/images/${pane.image.id}/checkpoints`);
  pane.image = data.image;
  const rows = data.checkpoints.map(checkpoint => {
    const created = new Date(checkpoint.created).toLocaleString();
    return `<li class="checkpoint-row" data-checkpoint="${esc(checkpoint.id)}">
      <span class="checkpoint-kind ${checkpoint.automatic ? "automatic" : "named"}" aria-hidden="true">${checkpoint.automatic ? "↶" : "●"}</span>
      <span class="checkpoint-details"><strong>${esc(checkpoint.name)}</strong><small>${checkpoint.automatic ? "Automatic undo point" : "Named checkpoint"} · ${esc(created)} · ${humanSize(checkpoint.size)}</small></span>
      <button class="row-action checkpoint-restore" type="button" title="Restore ${esc(checkpoint.name)}" aria-label="Restore ${esc(checkpoint.name)}">↶</button>
      <button class="row-action delete checkpoint-delete" type="button" title="Delete ${esc(checkpoint.name)}" aria-label="Delete ${esc(checkpoint.name)}">×</button>
    </li>`;
  }).join("");
  showModal(`
    <div class="checkpoint-heading"><div><small>IMAGE HISTORY</small><h2>Checkpoints</h2></div><span>${data.checkpoints.length} saved</span></div>
    <p>Create a permanent named checkpoint before a larger experiment, or restore any recent automatic undo point.</p>
    <div class="field"><label>New checkpoint name · max 60 characters</label><input name="name" maxlength="60" placeholder="Before reorganising Games" required></div>
    <ul class="checkpoint-list">${rows || '<li class="checkpoint-empty">No checkpoints yet. Image-changing operations will add automatic undo points here.</li>'}</ul>
    <div class="help-note"><strong>Storage:</strong> checkpoints stay inside this browser-owned working session. Large images use fast copy-on-write clones where available, with a sparse safe-copy fallback for zero-filled HDD capacity.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Close</button><button class="button primary" value="create">Create named checkpoint</button></div>`,
  async form => {
    const result = await api(`/api/images/${pane.image.id}/checkpoints`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: form.get("name") })
    });
    pane.image = result.image;
    renderPane(index, true);
    toast(`Checkpoint “${result.checkpoint.name}” created`);
    setTimeout(() => showCheckpointManager(index), 0);
  });
  modalContent.querySelectorAll(".checkpoint-restore").forEach(button => {
    button.onclick = async () => {
      const row = button.closest("[data-checkpoint]");
      const checkpoint = data.checkpoints.find(item => item.id === row.dataset.checkpoint);
      if (!checkpoint || !await confirmChoice("Restore this checkpoint?", `The image will be returned to “${checkpoint.name}”.`, { confirmLabel: "Restore", note: "The current state is kept as an automatic undo point first, so this can itself be undone." })) return;
      modal.close();
      try {
        const result = await paneOperation(index, `Restoring ${checkpoint.name}…`, () => api(
          `/api/images/${pane.image.id}/checkpoints/${checkpoint.id}/restore`,
          { method: "POST" }
        ));
        await reloadImageAfterRestore(result.image);
        toast(`Restored “${checkpoint.name}”`);
      } catch (error) {
        toast(`Could not restore checkpoint: ${error.message}`, true);
      }
    };
  });
  modalContent.querySelectorAll(".checkpoint-delete").forEach(button => {
    button.onclick = async () => {
      const row = button.closest("[data-checkpoint]");
      const checkpoint = data.checkpoints.find(item => item.id === row.dataset.checkpoint);
      if (!checkpoint || !await confirmChoice("Delete this checkpoint?", `“${checkpoint.name}” will no longer be available to restore.`, { confirmLabel: "Delete checkpoint", danger: true })) return;
      button.disabled = true;
      try {
        const result = await api(
          `/api/images/${pane.image.id}/checkpoints/${checkpoint.id}`,
          { method: "DELETE" }
        );
        pane.image = result.image;
        modal.close();
        renderPane(index, true);
        toast(`Checkpoint “${checkpoint.name}” deleted`);
        setTimeout(() => showCheckpointManager(index), 0);
      } catch (error) {
        button.disabled = false;
        toast(`Could not delete checkpoint: ${error.message}`, true);
      }
    };
  });
}

function trackFileInput(input, summary) {
  const state = { files: [] };
  const render = files => {
    state.files = [...files];
    summary.replaceChildren();
    if (!state.files.length) {
      const empty = document.createElement("span");
      empty.className = "file-selection-empty";
      empty.textContent = "No files selected yet · files can also be dropped here";
      summary.append(empty);
    } else {
      for (const file of state.files) {
        const row = document.createElement("span");
        const name = document.createElement("strong");
        name.textContent = file.name;
        row.append(name, document.createTextNode(` · ${humanSize(file.size)}`));
        summary.append(row);
      }
    }
    summary.classList.toggle("has-files", Boolean(state.files.length));
    summary.classList.remove("chooser-failed");
    summary.dispatchEvent(new CustomEvent("selectionchange"));
  };
  state.setFiles = render;
  const sync = () => render(input.files);
  input.addEventListener("change", sync);
  input.addEventListener("input", sync);
  input.addEventListener("click", () => {
    window.addEventListener("focus", () => {
      setTimeout(() => {
        if (input.files.length || state.files.length) return;
        summary.replaceChildren();
        const warning = document.createElement("span");
        warning.className = "file-selection-empty";
        warning.textContent = "Firefox returned no file. Try dropping the file here instead.";
        summary.append(warning);
        summary.classList.add("chooser-failed");
      }, 300);
    }, { once: true });
  });
  render([]);
  return state;
}

function acceptFileDrop(zone, onFiles) {
  zone.addEventListener("dragover", event => {
    if (!event.dataTransfer?.types.includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    zone.classList.add("drop-target");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("drop-target"));
  zone.addEventListener("drop", event => {
    zone.classList.remove("drop-target");
    const files = [...(event.dataTransfer?.files || [])];
    if (!files.length) return;
    event.preventDefault();
    onFiles(files);
  });
}

function chooseImage(index) {
  const pane = panes[index];
  if (pane.loading) return;
  const nativeChooser = window.webkit?.messageHandlers?.atariDesktop;
  if (nativeChooser?.postMessage) {
    nativeChooser.postMessage(`open-images:${index}`);
    return;
  }
  let selection = { files: [] };
  showModal(`
    <h2>Open a media image</h2>
    <p>Choose a floppy container, a hard-disk image, a CD or a ROM. A hard-disk image is a single file with its partition table inside it, and ZIP distributions are also supported.</p>
    <div class="field"><label>Image file</label>
      <input type="file" name="images" accept="${esc(formats.accept)}" multiple>
      <div class="file-selection-summary" data-selected-files aria-live="polite"></div>
    </div>
    <div class="field"><label>Target media</label>
      <select name="targetHardware">
        ${TARGET_MEDIA.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
      </select>
      <small>Used for validation and for hardware-safe repairs. It is ignored when the bytes already say what the image is.</small>
    </div>
    <div class="field"><label>Raw format override</label><select name="formatOverride"><option value="">Auto-detect</option><option value="rom">Open selected bytes as an Atari ROM</option></select><small>Use this for a headerless cartridge or expansion ROM stored as BIN or another generic name. No filesystem probing will be attempted.</small></div>
    <div class="modal-actions">
      <button class="button ghost" value="cancel">Cancel</button>
      <button class="button primary" value="open" data-open-selection disabled>Open selected image</button>
    </div>`,
  form => {
    const files = selection.files;
    if (!files.length) throw new Error("Choose a media image to open.");
    // Let showModal finish closing this dialog before the target-media
    // dialog is opened. Opening the replacement synchronously here lets the
    // first dialog's promise handler close the new one as well.
    const targetHardware = form.get("targetHardware") || "auto";
    if (form.get("formatOverride") === "rom") files.forEach(file => { file.atariForceKind = "rom"; });
    setTimeout(() => openFiles(index, files, targetHardware), 0);
  });
  const selectionSummary = modalContent.querySelector("[data-selected-files]");
  const openSelection = modalContent.querySelector("[data-open-selection]");
  selection = trackFileInput(
    modalContent.querySelector('input[name="images"]'),
    selectionSummary
  );
  acceptFileDrop(selectionSummary, files => selection.setFiles(files));
  selectionSummary.addEventListener("selectionchange", () => {
    openSelection.disabled = !selection.files.length;
  });
}

//: What the image is meant to be, which decides how it is validated and
//: which repairs are safe. A floppy container, a partitioned hard drive, a
//: single bare volume with no partition table, or a TOS ROM.
const TARGET_MEDIA = Object.freeze([
  ["auto", "Auto · identify from the bytes"],
  ["floppy", "Floppy · 360K to 1.44M, FAT12"],
  ["hd", "Hard drive · AHDI or MBR partitions"],
  ["volume", "Bare volume · one FAT16 partition with no table"],
  ["tos", "TOS ROM"],
]);

function promptTargetMedia(index, files) {
  const closed = showModal(`
    <h2>Choose the target media</h2>
    <p>What the image is meant to be decides how its filing system is checked and which repairs are safe. Choose the shape the finished image should have.</p>
    <div class="field"><label>Target media</label>
      <select name="targetHardware">
        ${TARGET_MEDIA.slice(1).concat([TARGET_MEDIA[0]]).map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
      </select>
    </div>
    <div class="help-note"><strong>A drive with a table, or one volume on its own:</strong> choose Hard drive for an image whose first sector holds an AHDI or MBR partition table, and Bare volume for a file that is nothing but the FAT16 volume itself, which some ACSI and IDE setups use.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="open">Validate and open</button></div>`,
  form => {
    const targetHardware = form.get("targetHardware") || "auto";
    setTimeout(() => openFiles(index, files, targetHardware), 0);
  });
}

async function openFiles(index, files, targetHardware = null) {
  if (!files.length) return;
  const romFiles = files.filter(file => formats.isRomImage(file.name) || file.atariForceKind === "rom");
  if (romFiles.length > 1) {
    const combinedSize = romFiles.reduce((total, file) => total + file.size, 0);
    if (combinedSize > 64 * 1024 * 1024) {
      toast("That ROM set is larger than the 64 MiB workbench safety limit.", true);
      return;
    }
    const equalSize = romFiles.every(file => file.size === romFiles[0].size);
    const canInterleave = equalSize && [2, 4].includes(romFiles.length);
    return showModal(`
      <h2>Open a ROM set</h2>
      <p>${romFiles.length} ROM components were selected. Keep the order shown below; physical chip numbering matters.</p>
      <div class="folder-import-preview">${romFiles.map((file, order) => `<code>${order + 1}. ${esc(file.name)} · ${humanSize(file.size)}</code>`).join("")}</div>
      <div class="field"><label>How are these files arranged?</label><select name="romSetMode">
        <option value="separate">Separate ROM images</option>
        <option value="concatenate">One component set · consecutive banks</option>
        ${canInterleave ? `<option value="interleave">${romFiles.length} byte-wide chips / interleave into logical byte order</option>` : ""}
        <option value="first">Open only the first selected file</option>
      </select><small>${canInterleave ? "A TOS ROM set is usually two byte-wide chips, one holding the even bytes and one the odd." : "Byte interleaving requires two or four components of exactly equal size."}</small></div>
      <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="open">Open selected ROMs</button></div>`,
    async form => {
      if (form.get("romSetMode") === "separate") {
        for (const [offset, file] of romFiles.entries()) {
          const target = offset === 0 ? index : addPane();
          await openFiles(target, [file], targetHardware);
        }
        return;
      }
      if (form.get("romSetMode") === "first") {
        setTimeout(() => openFiles(index, [romFiles[0]], targetHardware), 0);
        return;
      }
      const buffers = await Promise.all(romFiles.map(file => file.arrayBuffer()));
      let bytes;
      let layout = "linear";
      if (form.get("romSetMode") === "interleave") {
        const parts = buffers.map(buffer => new Uint8Array(buffer));
        bytes = new Uint8Array(parts[0].length * parts.length);
        for (let offset = 0; offset < parts[0].length; offset += 1) {
          for (let chip = 0; chip < parts.length; chip += 1) bytes[offset * parts.length + chip] = parts[chip][offset];
        }
        layout = `byte-interleaved-${parts.length}`;
      } else {
        bytes = new Uint8Array(buffers.reduce((sum, buffer) => sum + buffer.byteLength, 0));
        let offset = 0;
        for (const buffer of buffers) { bytes.set(new Uint8Array(buffer), offset); offset += buffer.byteLength; }
      }
      const combined = new File([bytes], `${formats.stem(romFiles[0].name)}-set.rom`, { type: "application/octet-stream" });
      combined.atariRomLayout = layout;
      combined.atariForceKind = "rom";
      combined.atariRomPlatform = layout === "linear" ? "tos" : "cartridge";
      combined.atariRomComponents = romFiles.map(file => file.name);
      setTimeout(() => openFiles(index, [combined], targetHardware), 0);
    });
  }
  const image = files[0];
  if (!image) return;
  if (targetHardware === null && formats.isPotentialGemdosImage(image.name)) {
    return promptTargetMedia(index, files);
  }
  targetHardware ||= "auto";
  const form = new FormData();
  form.append("image", image);
  form.append("targetHardware", targetHardware);
  if (image.atariForceKind) form.append("forceKind", image.atariForceKind);
  if (image.atariRomLayout) {
    form.append("romLayout", image.atariRomLayout);
    form.append("romPlatform", image.atariRomPlatform || "custom");
    form.append("romComponentNames", JSON.stringify(image.atariRomComponents || []));
  }
  setLoading(index, true, `Uploading and opening ${image.name}…`);
  try {
    const data = await uploadApi("/api/images", form, {
      onProgress: (loaded, total) => {
        const progress = total
          ? ` · ${Math.min(100, Math.round(loaded * 100 / total))}%`
          : ` · ${humanSize(loaded)}`;
        setLoading(index, true, `Uploading ${image.name}${progress}`);
      },
      onProcessing: () => setLoading(
        index,
        true,
        `Upload complete · opening ${image.name}…`
      )
    });
    await acceptImage(index, data.image);
    if (image.atariRomLayout) {
      const configured = await api(`/api/images/${data.image.id}/rom-layout`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bankSize: data.image.rom?.bankSize || 16384,
          eraseByte: data.image.rom?.eraseByte ?? 255,
          platform: image.atariRomPlatform,
          layout: image.atariRomLayout,
        }),
      });
      panes[index].image = configured.image;
      await loadDirectory(index);
    }
    toast(`${data.image.name} opened`);
  } catch (error) {
    panes[index].loading = false;
    panes[index].loadingMessage = "";
    renderPane(index);
    toast(error.message, true);
  }
}

//: The Workbench hardware profile is the workspace default, so an image that
//: carries none of its own takes it as it opens. Before this, every new image
//: started as a bare 520ST however the workspace was set, and the only way to
//: correct it was a trip to Workbench -> Hardware profiles for each pane in
//: turn, which made testing anything awkward. An image that already has a
//: profile keeps it: this fills a gap, it does not overrule a choice.
async function applyWorkspaceProfile(image) {
  if (!image?.id || image.hardwareProfile?.machine) return image;
  const { profile } = activeWorkbenchProfile();
  if (!profile?.machine) return image;
  // Target validation belongs to the media rather than to the machine, and
  // opening or creating the image has already settled it, so it is left as it
  // was found.
  const { targetHardware, ...machine } = profile;
  try {
    const data = await api(`/api/images/${image.id}/hardware-profile`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(machine),
    });
    return data.image;
  } catch (error) {
    // A profile that will not apply is no reason to refuse the image.
    return image;
  }
}

async function acceptImage(index, image) {
  image = await applyWorkspaceProfile(image);
  const currentPane = panes[index];
  const preservedWindowState = currentPane?.windowState || null;
  const preserveDriveRoot = Boolean(
    currentPane?.image?.id === image.id
    && currentPane.image.kind === "hd"
    && currentPane.partition === null
  );
  const preservedSelection = preserveDriveRoot ? selectionKeys(currentPane) : [];
  const preservedAnchor = preserveDriveRoot ? currentPane.selectionAnchor : null;
  const preservedScrollTop = preserveDriveRoot
    ? document.querySelector(`.pane[data-pane="${index}"] .list-wrap`)?.scrollTop || 0
    : 0;
  panes[index] = newPaneState(image);
  const pane = panes[index];
  pane.windowState = preservedWindowState;
  if (preserveDriveRoot) pane.driveScrollTop = preservedScrollTop;
  const requestToken = ++pane.requestToken;
  renderPane(index);
  if (image.kind === "hd") {
    const [data, capacity, partitionTable] = await Promise.all([
      api(`/api/images/${image.id}/partitions`),
      fetchCapacity(image.id),
      fetchPartitionTable(image.id),
    ]);
    if (panes[index] !== pane || pane.requestToken !== requestToken) return;
    pane.entries = data.partitions;
    pane.capacity = capacity;
    pane.partitionTable = partitionTable;
    pane.description = paneTableDescription(pane);
    pane.loading = false;
    if (preserveDriveRoot) {
      const available = new Set(pane.entries.map(entry => String(entry.partition)));
      setSelection(pane, preservedSelection.filter(key => available.has(key)), preservedAnchor);
    }
    renderPane(index);
    if (preserveDriveRoot) {
      const list = document.querySelector(`.pane[data-pane="${index}"] .list-wrap`);
      if (list) list.scrollTop = preservedScrollTop;
    }
  } else {
    await loadDirectory(index);
  }
  if (image.warnings?.length) {
    const latest = image.warnings.at(-1);
    toast(
      image.warnings.length === 1
        ? latest
        : `${image.warnings.length} image notices are recorded. Latest: ${latest}`,
      true,
    );
  }
}

async function loadDirectory(index, preserveSelection = false) {
  const pane = panes[index];
  const requestToken = (pane.requestToken || 0) + 1;
  pane.requestToken = requestToken;
  const requested = {
    image: pane.image.id,
    partition: pane.partition,
    side: pane.side,
    path: pane.path,
    archivePath: pane.archivePath,
    archiveMember: pane.archiveMember,
  };
  const selected = selectionKeys(pane);
  const selectionAnchor = pane.selectionAnchor;
  pane.loading = true;
  pane.loadingMessage = pane.loadingMessage || "Reading disk…";
  if (!preserveSelection) setSelection(pane, []);
  renderPane(index);
  try {
    const query = new URLSearchParams(pane.archivePath ? {
      path: pane.archivePath,
      name: pane.archiveName,
      member: pane.archiveMember || "",
    } : { path: pane.path });
    if (pane.partition !== null) query.set("partition", pane.partition);
    if (pane.side !== null) query.set("side", pane.side);
    const data = await api(`/api/images/${pane.image.id}/${pane.archivePath ? "archive/tree" : "tree"}?${query}`);
    if (
      panes[index] !== pane || pane.requestToken !== requestToken ||
      pane.image.id !== requested.image || pane.partition !== requested.partition ||
      pane.side !== requested.side || pane.path !== requested.path
      || pane.archivePath !== requested.archivePath || pane.archiveMember !== requested.archiveMember
    ) return;
    pane.entries = data.entries;
    pane.capacity = data.capacity || pane.capacity;
    pane.description = data.description;
    if (pane.archivePath) pane.archiveKind = data.archiveKind || "archive";
    if (preserveSelection) setSelection(pane, selected, selectionAnchor);
  } catch (error) {
    if (panes[index] === pane && pane.requestToken === requestToken) toast(error.message, true);
  } finally {
    if (panes[index] !== pane || pane.requestToken !== requestToken) return;
    pane.loading = false;
    pane.loadingMessage = "";
    renderPane(index);
  }
}

function navigate(index, path) {
  panes[index].path = path;
  return loadDirectory(index);
}

function removePane(index) {
  const pane = panes[index];
  if (!pane) return;
  const imageName = pane.image?.name;
  captureActiveEditorDocument();
  const rebuiltDocuments = new Map();
  let rebuiltActive = editorWorkspace.state.active;
  for (const document of editorDocuments.values()) {
    if (document.index === index) {
      if (document.key === editorWorkspace.state.active) rebuiltActive = null;
      continue;
    }
    const nextIndex = document.index > index ? document.index - 1 : document.index;
    const nextKey = [nextIndex, document.imageId, document.partition ?? "-", document.side ?? "-", document.path].join("|");
    if (document.key === editorWorkspace.state.active) rebuiltActive = nextKey;
    rebuiltDocuments.set(nextKey, { ...document, index: nextIndex, key: nextKey });
  }
  editorDocuments.clear();
  rebuiltDocuments.forEach((document, key) => editorDocuments.set(key, document));
  editorWorkspace.state.active = rebuiltActive;
  persistEditorDocuments();
  panes.splice(index, 1);
  rebuildPaneHosts();
  rememberOpenPanes();
  if (imageName) toast(`${imageName} closed · its working copy remains available in Recovery.`);
}

async function closePane(index) {
  const pane = panes[index];
  if (!pane) return;
  if (panes.some(item => item.loading || item.actionPending)) {
    return toast("Wait for current pane operations to finish before closing a pane.", true);
  }
  if (!pane.image?.dirty) {
    removePane(index);
    return;
  }
  let closeAction = "save";
  showModal(`
    <h2>Save ${esc(pane.image.name)} before closing?</h2>
    <p>This working image contains changes. Save a timestamped image and README ZIP now, discard the download, or cancel and keep the pane open.</p>
    <div class="help-note"><strong>Recovery remains available:</strong> closing a pane does not delete its private server-side working copy.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button danger" data-close-without-saving value="discard">Close without saving</button><button class="button primary" value="save">Save and close</button></div>`,
  async () => {
    if (closeAction === "discard") {
      removePane(index);
      return;
    }
    if (!await saveImage(index)) return false;
    removePane(index);
  });
  modalContent.querySelector("[data-close-without-saving]").onclick = () => {
    closeAction = "discard";
  };
}

function beginImageRename(index) {
  const pane = panes[index];
  if (!pane.image || pane.loading || pane.actionPending) return;
  const host = document.querySelector(`.pane[data-pane="${index}"]`);
  const title = host.querySelector(".image-title");
  if (!title) return;

  const input = document.createElement("input");
  input.className = "image-title-input";
  input.type = "text";
  input.maxLength = 180;
  input.value = pane.image.name;
  input.setAttribute("aria-label", "Image filename");
  title.replaceWith(input);
  input.focus();
  const extensionAt = input.value.lastIndexOf(".");
  input.setSelectionRange(0, extensionAt > 0 ? extensionAt : input.value.length);

  let finished = false;
  const cancel = () => {
    if (finished) return;
    finished = true;
    renderPane(index, true);
  };
  const commit = async () => {
    if (finished) return;
    const name = input.value.trim();
    if (!name || name === pane.image.name) {
      cancel();
      return;
    }
    finished = true;
    try {
      const data = await paneOperation(index, "Renaming image…", () => api(`/api/images/${pane.image.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name })
      }));
      pane.image = data.image;
      renderPane(index, true);
      toast(`Image renamed to ${data.image.name}`);
    } catch (error) {
      renderPane(index, true);
      toast(`Could not rename image: ${error.message}`, true);
    }
  };
  input.addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      commit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancel();
    }
  });
  input.addEventListener("blur", commit);
}

async function showRomStructure(index, bankNumber, restoreState = null, { replace = false } = {}) {
  const pane = panes[index];
  const summary = pane.entries.find(item => Number(item.bank) === Number(bankNumber));
  if (!summary) return toast("That ROM bank is no longer available.", true);
  const data = await api(`/api/images/${pane.image.id}/rom-banks/${Number(bankNumber)}/inspect`);
  const entry = data.bank;
  const bankSize = Number(pane.image.rom?.bankSize || 16384);
  const bankOffset = Number(entry.bank) * bankSize;
  const hex = (value, width = 4) => Number(value).toString(16).toUpperCase().padStart(width, "0");
  const header = entry.header;
  const extension = entry.extensionHeader;
  const structures = entry.structures || [];
  const strings = entry.strings || [];
  const diagnostics = entry.diagnostics || {};
  const modules = entry.modules || [];
  const starCommands = entry.starCommands || [];
  const erasedPercent = entry.length ? (100 * Number(diagnostics.erasedBytes || 0) / entry.length).toFixed(1) : "0.0";
  const headerRows = header ? [
    ["Title", header.title],
    ["Version text", header.version || "Not supplied"],
    // The Atari records its release as a 16-bit word at offset 2, not as a
    // byte, and there is no type byte anywhere in the header. Asking for
    // fields the decoder does not produce printed "&NAN" and "&undefined".
    ["Version word", `&${header.versionHex}`],
    ["Copyright", header.copyright],
    ["ROM type", header.roles || "Not identified"],
    ["Processor", header.processor],
    // A TOS header carries no language or service entry; those two rows named
    // fields the decoder never produced, so both always read "Not present".
    // These are the pointers the header really does declare.
    ["Operating system base", header.base == null ? "Not declared" : `&${hex(header.base)}`],
    ["Reset entry", header.resetEntry == null ? "Not declared" : `&${hex(header.resetEntry)}`],
    ["Built", header.date || "Not declared"],
    ["Country and video", [header.country, header.videoStandard].filter(Boolean).join(" · ") || "Not declared"],
    ["Extra features", header.features?.length ? header.features.join(", ") : "None declared"],
  ] : [];
  const structureRows = structures.map(item => `
    <tr><td>${esc(item.name)}</td><td><code>+&${hex(item.offset)}</code>${item.address == null ? "" : ` · mapped <code>&${hex(item.address)}</code>`}</td><td>${item.length == null ? "Entry point" : humanSize(item.length)}</td><td><button class="button compact rom-open-offset" type="button" data-offset="${bankOffset + Number(item.offset)}">Hex</button></td></tr>`).join("");
  const stringRows = strings.map(item => `
    <tr><td><code>+&${hex(item.offset)}</code></td><td><code>&${hex(item.address)}</code></td><td>${esc(item.text)}</td><td><button class="button compact rom-open-offset" type="button" data-offset="${bankOffset + Number(item.offset)}">Hex</button></td></tr>`).join("");
  const moduleRows = modules.map(item => `
    <tr><td><strong>${esc(item.title)}</strong>${item.help ? `<small>${esc(item.help)}</small>` : ""}</td><td><code>+&${hex(item.offset)}</code></td><td>${[
      item.start != null ? "start" : "", item.initialise != null ? "init" : "", item.finalise != null ? "final" : "", item.service != null ? "service" : "", item.commands != null ? "commands" : "", item.swiHandler != null ? "SWIs" : ""
    ].filter(Boolean).join(", ") || "metadata only"}</td><td><button class="button compact rom-open-offset" type="button" data-offset="${bankOffset + Number(item.offset)}">Hex</button></td></tr>`).join("");
  const commandRows = starCommands.map((item, helpIndex) => {
    const detail = item.confidence === "declared"
      ? `${item.module ? `Declared by ${item.module}. ` : ""}${item.configureKeyword ? "Configuration and status keyword" : item.filingSystemCommand ? "Filing-system command" : "Module command"}${item.minimumParameters == null ? "" : ` · ${item.minimumParameters} to ${item.maximumParameters} parameter${item.maximumParameters === 1 ? "" : "s"}`}`
      : item.handlerAddress != null
        ? `Cartridge application chain · handler $${hex(item.handlerAddress)}`
        : `Cartridge application name table${item.token == null ? "" : ` · entry $${hex(item.token, 2)}`}`;
    const helpButton = item.helpText
      ? `<button class="rom-command-help" type="button" data-help-index="${helpIndex}" aria-label="Help for ${esc(item.display)}" aria-describedby="rom-command-help-tooltip" aria-expanded="false">?</button>`
      : "";
    return `<tr><td><span class="rom-command-name"><strong><code>${esc(item.display)}</code></strong>${helpButton}</span></td><td><span class="rom-command-confidence">${esc(item.confidence)}</span><small>${esc(detail)}</small></td><td><code>+&${hex(item.offset)}</code>${item.address == null ? "" : ` · &${hex(item.address)}`}</td><td><span class="rom-command-actions"><button class="button compact rom-open-offset" type="button" data-offset="${bankOffset + Number(item.offset)}">Table</button>${item.handlerOffset == null ? "" : `<button class="button compact rom-open-offset" type="button" data-offset="${bankOffset + Number(item.handlerOffset)}">Handler</button>`}</span></td></tr>`;
  }).join("");
  showModal(`
    <div class="modal-heading rom-decoder-heading" tabindex="-1" autofocus><span class="modal-kicker">DECODED ROM CONTENTS</span><h2>Bank ${entry.bank} · ${esc(entry.name)}</h2><p>This is a byte-addressed ROM bank, not a filing-system directory. Only proven structures are named; printable runs are evidence, not invented files.</p></div>
    <div class="rom-summary-grid">
    <section class="rom-decode-section"><h3>Bank fingerprint and programming information</h3><dl class="rom-header-grid"><dt>Image byte range</dt><dd><code>&${hex(bankOffset, 6)} to &${hex(bankOffset + entry.length - 1, 6)}</code></dd><dt>SHA-256</dt><dd><code>${esc(diagnostics.sha256 || "Unavailable")}</code></dd><dt>CRC-32</dt><dd><code>&${esc(diagnostics.crc32 || "Unavailable")}</code></dd><dt>Information entropy</dt><dd>${Number(diagnostics.entropy || 0).toFixed(3)} bits per byte (0 to 8)</dd><dt>Distinct byte values</dt><dd>${Number(diagnostics.uniqueByteValues || 0)} of 256</dd><dt>Erased bytes</dt><dd>${Number(diagnostics.erasedBytes || 0).toLocaleString()} (${erasedPercent}%) using <code>&${hex(pane.image.rom?.eraseByte ?? 255, 2)}</code></dd><dt>Used range</dt><dd>${diagnostics.usedStart == null ? "Entire bank is erased" : `<code>+&${hex(diagnostics.usedStart)} to +&${hex(diagnostics.usedEnd)}</code>`}</dd><dt>Zero / &amp;FF bytes</dt><dd>${Number(diagnostics.zeroBytes || 0).toLocaleString()} / ${Number(diagnostics.ffBytes || 0).toLocaleString()}</dd><dt>Printable bytes</dt><dd>${Number(diagnostics.printableBytes || 0).toLocaleString()}</dd><dt>Identical banks</dt><dd>${entry.matchingBanks?.length ? entry.matchingBanks.map(bank => `Bank ${bank}`).join(", ") : "None"}</dd></dl></section>
    ${header ? `<section class="rom-decode-section"><h3>Atari ROM header</h3><dl class="rom-header-grid">${headerRows.map(([label, value]) => `<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`).join("")}</dl></section>` : '<div class="help-note"><strong>No recognised Atari ROM header:</strong> the bank remains available as raw code and data.</div>'}
    ${extension ? `<section class="rom-decode-section rom-extension-section"><h3>Cartridge header</h3><dl class="rom-header-grid"><dt>Declared image size</dt><dd>${humanSize(extension.declaredSize)}</dd><dt>Stored checksum</dt><dd><code>&${hex(extension.checksum, 8)}</code></dd><dt>Calculated checksum</dt><dd><code>&${hex(extension.calculatedChecksum, 8)}</code></dd><dt>Result</dt><dd>${extension.checksumValid ? "Valid" : "INVALID"}</dd></dl></section>` : ""}
    </div>
    ${entry.warnings?.length ? `<div class="help-warning"><strong>Header consistency warning:</strong><ul>${entry.warnings.map(warning => `<li>${esc(warning)}</li>`).join("")}</ul></div>` : ""}
    <section class="rom-decode-section"><h3>Cartridge applications and modules</h3>${starCommands.length ? `<p>A cartridge application declared by the <code>$ABCDEF42</code> header magic is listed with the name and the entry point its chain points at. Anything else is listed only when a structurally valid name or vector table is found; printable text alone is not included. A <strong>?</strong> opens help declared by the ROM or a signature reconstructed from its own tables.</p><div class="rom-decode-table"><table><thead><tr><th>Command</th><th>Evidence</th><th>Table location</th><th></th></tr></thead><tbody>${commandRows}</tbody></table></div>` : `<div class="help-note"><strong>No modules could be listed safely.</strong> This does not prove the ROM has none: an expansion ROM can build its chain at run time, or use a table this scanner does not recognise.</div>`}</section>
    <section class="rom-decode-section"><h3>Known regions and entry points</h3><div class="rom-decode-table"><table><thead><tr><th>Meaning</th><th>Location</th><th>Extent</th><th></th></tr></thead><tbody>${structureRows || '<tr><td colspan="4">This bank is erased and contains no decoded structures.</td></tr>'}</tbody></table></div></section>
    ${modules.length ? `<section class="rom-decode-section"><h3>Structurally plausible TOS modules</h3><p>These candidates passed the standard module-header offset and title checks. They are reported as candidates until their enclosing cartridge or expansion chunk is fully identified.</p><div class="rom-decode-table"><table><thead><tr><th>Module</th><th>Offset</th><th>Declared facilities</th><th></th></tr></thead><tbody>${moduleRows}</tbody></table></div></section>` : ""}
    <details class="rom-string-list" ${strings.length <= 20 ? "open" : ""}><summary>${entry.stringsTruncated ? "First " : ""}${strings.length} printable string${strings.length === 1 ? "" : "s"} ${entry.stringsTruncated ? "shown" : "found"}</summary><p>Strings often reveal commands, messages and build information, but their boundaries do not make them files.${entry.stringsTruncated ? " The display is capped at 512 candidates per bank to keep the browser responsive; use hex search for the remainder." : ""}</p><div class="rom-decode-table"><table><thead><tr><th>Offset</th><th>Mapped address</th><th>Text</th><th></th></tr></thead><tbody>${stringRows || '<tr><td colspan="4">No printable strings of four or more characters were found.</td></tr>'}</tbody></table></div></details>
    <div id="rom-command-help-tooltip" class="rom-command-tooltip" role="tooltip" hidden></div>
    <div class="modal-actions"><button class="button ghost rom-open-offset" type="button" data-offset="${bankOffset}">Open whole bank in hex editor</button><button class="button primary" value="cancel">Close</button></div>`, undefined, { replace });
  modalContent.querySelectorAll(".rom-open-offset").forEach(button => {
    button.addEventListener("click", async () => {
      const offset = Number(button.dataset.offset || bankOffset);
      const decoderForm = modal.querySelector("form");
      if (!decoderForm || modal.classList.contains("hex-editor-modal-host")) return;
      const returnState = {
        formScrollTop: decoderForm?.scrollTop || 0,
        tables: [...modalContent.querySelectorAll(".rom-decode-table")].map(table => ({
          scrollTop: table.scrollTop,
          scrollLeft: table.scrollLeft,
        })),
        details: [...modalContent.querySelectorAll("details")].map(details => details.open),
        focusOffset: button.dataset.offset,
      };
      let decoderChanged = false;
      modal.classList.add("hex-editor-modal-host");
      decoderForm.inert = true;
      try {
        await openHexEditor(index, offset, {
          host: modal,
          pageSize: 512,
          afterSave: () => { decoderChanged = true; },
          onClose: async () => {
            modal.classList.remove("hex-editor-modal-host");
            decoderForm.inert = false;
            if (decoderChanged) {
              await showRomStructure(index, bankNumber, returnState, { replace: true });
              return;
            }
            decoderForm.scrollTop = returnState.formScrollTop;
            button.focus({ preventScroll: true });
          },
        });
      } catch (error) {
        modal.classList.remove("hex-editor-modal-host");
        decoderForm.inert = false;
        toast(`Could not open the hex editor: ${error.message}`, true);
      }
    });
  });
  const helpTooltip = modalContent.querySelector(".rom-command-tooltip");
  const helpButtons = [...modalContent.querySelectorAll(".rom-command-help")];
  let pinnedHelpButton = null;
  const hideCommandHelp = (button, force = false) => {
    if (!force && pinnedHelpButton === button) return;
    button?.setAttribute("aria-expanded", "false");
    if (force || !pinnedHelpButton) helpTooltip.hidden = true;
  };
  const showCommandHelp = (button, pin = false) => {
    if (pinnedHelpButton && pinnedHelpButton !== button && !pin) return;
    const item = starCommands[Number(button.dataset.helpIndex)];
    if (!item?.helpText) return;
    if (pinnedHelpButton && pinnedHelpButton !== button) pinnedHelpButton.setAttribute("aria-expanded", "false");
    if (pin) pinnedHelpButton = button;
    helpTooltip.innerHTML = `<strong>${esc(item.helpText)}</strong><small>${esc(item.helpSource || "Help recovered from the ROM")}</small>`;
    helpTooltip.hidden = false;
    button.setAttribute("aria-expanded", "true");
    const anchor = button.getBoundingClientRect();
    const tooltip = helpTooltip.getBoundingClientRect();
    const gutter = 10;
    const left = Math.max(gutter, Math.min(anchor.left, window.innerWidth - tooltip.width - gutter));
    const below = anchor.bottom + 7;
    const top = below + tooltip.height <= window.innerHeight - gutter
      ? below
      : Math.max(gutter, anchor.top - tooltip.height - 7);
    helpTooltip.style.left = `${left}px`;
    helpTooltip.style.top = `${top}px`;
  };
  helpButtons.forEach(button => {
    button.addEventListener("pointerenter", () => showCommandHelp(button));
    button.addEventListener("pointerleave", () => hideCommandHelp(button));
    button.addEventListener("focus", () => showCommandHelp(button));
    button.addEventListener("blur", () => hideCommandHelp(button));
    button.addEventListener("click", () => {
      if (pinnedHelpButton === button) {
        pinnedHelpButton = null;
        hideCommandHelp(button, true);
      } else {
        showCommandHelp(button, true);
      }
    });
  });
  modalContent.addEventListener("keydown", event => {
    if (event.key === "Escape" && pinnedHelpButton) {
      event.preventDefault();
      event.stopPropagation();
      const button = pinnedHelpButton;
      pinnedHelpButton = null;
      hideCommandHelp(button, true);
      button.focus();
    }
  });
  if (restoreState) {
    setTimeout(() => {
      const decoderForm = modal.querySelector("form");
      modalContent.querySelectorAll("details").forEach((details, detailIndex) => {
        if (restoreState.details?.[detailIndex] != null) details.open = restoreState.details[detailIndex];
      });
      modalContent.querySelectorAll(".rom-decode-table").forEach((table, tableIndex) => {
        const tableState = restoreState.tables?.[tableIndex];
        if (!tableState) return;
        table.scrollTop = tableState.scrollTop || 0;
        table.scrollLeft = tableState.scrollLeft || 0;
      });
      if (decoderForm) decoderForm.scrollTop = restoreState.formScrollTop || 0;
      const returnControl = restoreState.focusOffset == null
        ? null
        : modalContent.querySelector(`.rom-open-offset[data-offset="${restoreState.focusOffset}"]`);
      returnControl?.focus({ preventScroll: true });
    }, 60);
  }
}

function renameSelected(index) {
  const pane = panes[index];
  const entry = selectedEntry(index);
  if (!entry) return;
  const isRom = pane.image.kind === "rom";
  const oldPath = entryImagePath(pane, entry);
  // A GEMDOS directory entry holds an 8.3 name and nothing longer; a ROM
  // header has its own limit.
  const rule = targetNameRule(pane, entry.leafName || entry.name);
  const nameLimit = isRom ? Number(entry.header?.titleCapacity || 24) : rule.limit;
  showModal(`
    <h2>${isRom ? `Edit ROM bank ${entry.bank} title` : `Rename ${esc(entry.name)}`}</h2>
    <p>${isRom ? "This changes the name in the recognised ROM header. The code and bank position stay unchanged." : `The item stays in its current folder. Drag it onto another folder to move it. TOS stores an ${esc(rule.label)} name in upper case.`}</p>
    <div class="field"><label>New name · max ${nameLimit} characters</label>
      <input name="destination" maxlength="${nameLimit}" value="${esc(entry.leafName || entry.name)}" required></div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="ok">Rename</button></div>`,
  async form => {
    const body = { partition: pane.partition, side: pane.side };
    if (isRom) { body.bank = entry.bank; body.title = form.get("destination"); }
    else {
      body.source = oldPath;
      body.destination = fullPath(pane.path, form.get("destination"));
    }
    const data = await api(`/api/images/${pane.image.id}/rename`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    });
    if (isRom) {
      pane.image = data.image;
      await loadDirectory(index);
    } else {
      await refreshSharedVolumePanes(pane.image.id, data.image, data.moved);
    }
    toast(
      "Name updated",
    );
  });
}

function deleteSelected(index) {
  const pane = panes[index];
  const isRom = pane.image.kind === "rom";
  const entries = selectedEntries(index);
  if (!entries.length) return;
  const single = entries.length === 1 ? entries[0] : null;
  const selectionLabel = single ? esc(single.name) : `${entries.length} selected items`;
  const contentsWarning = entries.some(
    item => item.type === "dir" || item.type === "directory"
  ) ? " Selected folders and everything inside them will be removed." : "";
  showModal(`
    <h2>${isRom ? "Erase" : "Delete"} ${selectionLabel}?</h2>
    <p>${isRom ? "Each selected bank will be filled with the configured erased-byte value. Bank positions and total ROM size stay unchanged." : `This removes ${single ? "the selected item" : "all selected items"} from the working image.${contentsWarning}`} Your original image remains untouched.</p>
    <div class="modal-actions"><button class="button ghost" value="cancel">Keep ${entries.length === 1 ? "it" : "them"}</button><button class="button danger" value="delete">Delete ${entries.length} item${entries.length === 1 ? "" : "s"}</button></div>`,
  async () => {
    const data = await api(`/api/images/${pane.image.id}/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        partition: pane.partition,
        side: pane.side,
        items: entries.map(item => ({
          path: isRom ? `bank:${item.bank}` : entryImagePath(pane, item),
          bank: isRom ? item.bank : undefined,
          recursive: item.type === "dir" || item.type === "directory",
        })),
      }),
    });
    if (isRom) {
      pane.image = data.image;
      await loadDirectory(index);
    } else {
      await refreshSharedVolumePanes(
        pane.image.id,
        data.image,
        [],
        data.deletedItems || [{ path: data.deletedPath, isDirectory: data.deletedDirectory }],
      );
    }
    toast(`${single ? single.name : `${entries.length} items`} deleted`);
  });
}

function createFolder(index) {
  const pane = panes[index];
  const rule = targetNameRule(pane, "NEWFOLDER");
  const driveLetter = pane.partitionName || pane.image.driveLetter || "";
  showModal(`
    <h2>New folder</h2><p>Create a folder in <code>${esc(drivePath(driveLetter, pane.path))}</code>. A folder carries an ${esc(rule.label)} name, stored in upper case.</p>
    <div class="field"><label>Folder name · max ${rule.limit} characters</label><input name="name" maxlength="${rule.limit}" required></div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="create">Create folder</button></div>`,
  async form => {
    const data = await paneOperation(index, "Creating folder…", () => api(`/api/images/${pane.image.id}/mkdir`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ partition: pane.partition, side: pane.side, path: fullPath(pane.path, form.get("name")) })
    }));
    pane.image = data.image;
    await loadDirectory(index);
    toast("Folder created");
  });
}

function createEmptyFile(index) {
  const pane = panes[index];
  const rule = targetNameRule(pane, "NEWFILE");
  showModal(`
    <h2>New file</h2>
    <p>Create an empty file in <code>${esc(pane.path)}</code>. ${esc(rule.label)} names can contain up to ${rule.limit} characters.</p>
    <div class="field"><label>Filename</label><input name="name" maxlength="${rule.limit}" value="${esc(rule.suggested || "NEWFILE")}" required></div>
    <div class="field-grid two"><div class="field"><label>Attributes</label><input name="attributes" value="-----a" maxlength="6"><small>The six letters <code>rhsvda</code>, a dash for each clear bit.</small></div><div class="field"><label>Datestamp</label><input name="datestamp" type="datetime-local" step="2"><small>Leave it empty to stamp the file with the current time.</small></div></div>
    <div class="help-note">The file starts at zero bytes. Its attributes and datestamp can be changed later from the file list.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="create">Create file</button></div>`,
  async form => {
    const data = await paneOperation(index, "Creating empty file…", () => api(`/api/images/${pane.image.id}/empty-file`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        partition: pane.partition,
        side: pane.side,
        destination: pane.path,
        name: form.get("name"),
        attributes: form.get("attributes") || "",
        datestamp: form.get("datestamp") || "",
      }),
    }));
    pane.image = data.image;
    await loadDirectory(index);
    setSelection(pane, [String(form.get("name"))], String(form.get("name")));
    renderPane(index);
    toast(`${form.get("name")} created`);
  });
}

//: What a datetime-local field wants: ISO text without a zone, whether the
//: listing gave the stamp as text or as the date and time words a GEMDOS
//: directory entry actually holds.
function datestampForInput(value) {
  const text = value && typeof value === "object" ? formatDatestamp(value) : String(value || "");
  return text.slice(0, 19).replace(" ", "T");
}

async function editFileMetadata(index, entry) {
  const pane = panes[index];
  if (!pane?.image || !entry) return;
  const path = entry.path || fullPath(pane.path, entry.leafName || entry.name);
  // GEMDOS keeps one attribute byte per directory entry: read-only, hidden,
  // system, volume label, directory and archive, in that bit order. None of
  // them is inverted, so each checkbox means exactly what it says.
  const flags = attributeFlags(entry.attributes ?? entry.attr ?? 0);
  const has = letter => Boolean(flags[letter]);
  const flag = (letter, label, hint) => `<label class="check"><input type="checkbox" name="bit-${letter}" ${has(letter) ? "checked" : ""}> ${label}<small>${hint}</small></label>`;
  // The stamp arrives as ISO text, or as the two GEMDOS words themselves,
  // and the browser wants it without a zone.
  const stamp = datestampForInput(entry.datestamp);
  return showModal(`
    <h2>Attributes and datestamp</h2>
    <p>Editing <code>${esc(path)}</code>. These are the fields a GEMDOS directory entry holds; the file's own bytes are not touched.</p>
    <div class="field-grid two">
      ${flag("r", "Read-only", "r · $01")}
      ${flag("h", "Hidden", "h · $02")}
      ${flag("s", "System", "s · $04")}
      ${flag("v", "Volume label", "v · $08")}
      ${flag("d", "Directory", "d · $10")}
      ${flag("a", "Archive", "a · $20")}
    </div>
    <div class="field"><label>Datestamp</label>
      <input name="datestamp" type="datetime-local" step="2" value="${esc(stamp)}">
      <small>TOS records the time to the nearest two seconds and cannot store a year before 1980.</small></div>
    <div class="help-note">The volume label and directory bits describe what the entry <em>is</em>. Changing either on an ordinary file makes it unreadable, so change them only when repairing a damaged directory.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="change">Save metadata</button></div>`,
  async form => {
    const chosen = {
      r: form.has("bit-r"), h: form.has("bit-h"), s: form.has("bit-s"),
      v: form.has("bit-v"), d: form.has("bit-d"), a: form.has("bit-a"),
    };
    const requested = String(form.get("datestamp") || "").trim();
    if (requested && !parseDatestamp(requested)) {
      throw new Error("TOS cannot store that datestamp. Use a date from 1980 onwards.");
    }
    const data = await paneOperation(index, `Updating metadata for ${entry.name}…`, () => api(`/api/images/${pane.image.id}/metadata`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path,
        partition: pane.partition,
        side: pane.side,
        attributes: attributeHex(chosen),
        datestamp: requested,
      }),
    }));
    pane.image = data.image;
    await loadDirectory(index);
    setSelection(pane, [entrySelectionKey(entry)], entrySelectionKey(entry));
    renderPane(index);
    toast(`${entry.name} now reads ${formatAttributes(chosen)}`);
  });
}

//: Ask the browser for host files without putting a control on screen.
//:
//: There is no way to open a file chooser except through an <input type=file>,
//: so every place that wants one builds the same throwaway element. Building
//: it in one place means the cancel case is handled once as well: without an
//: `oncancel` handler the promise never settles, and the caller waits for a
//: choice the operator has already declined to make.
function pickHostFiles({ directory = false, accept = "" } = {}) {
  return new Promise(resolve => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    if (directory) {
      input.setAttribute("webkitdirectory", "");
      input.setAttribute("directory", "");
      // The Linux desktop host runs the page inside WebKitGTK, whose file
      // chooser has no concept of a directory: the attributes above are
      // ignored and an ordinary file chooser opens, which an operator cannot
      // pick a folder in. Telling the host first lets it answer this one
      // request with a real folder chooser. In a browser there is no handler
      // to tell, and the attributes work on their own.
      window.webkit?.messageHandlers?.atariDesktop?.postMessage("expect-folder");
    }
    if (accept) input.accept = accept;
    input.onchange = () => resolve([...input.files]);
    input.oncancel = () => resolve([]);
    input.click();
  });
}

//: Host files carry their position in the chosen folder, which is what an
//: import needs to rebuild the tree on the Atari side.
const hostFolderRecords = files => files.map(file => ({
  file,
  relativePath: file.webkitRelativePath || file.name,
}));

async function chooseHostFile(index) {
  const files = await pickHostFiles();
  if (files.length) addSelectedHostFiles(index, files);
}

async function chooseHostFolder(index) {
  // A drive showing its partition table has nowhere to put an ordinary file,
  // so only whole disk images are worth offering there.
  const atPartitionTable = panes[index].image?.kind === "hd" && panes[index].partition === null;
  const files = await pickHostFiles({
    directory: true,
    accept: atPartitionTable ? formats.accept : "",
  });
  if (files.length) addSelectedHostFolder(index, hostFolderRecords(files));
}

function readDroppedDirectory(entry) {
  const reader = entry.createReader();
  const children = [];
  return new Promise((resolve, reject) => {
    const readBatch = () => reader.readEntries(batch => {
      if (!batch.length) return resolve(children);
      children.push(...batch);
      readBatch();
    }, reject);
    readBatch();
  });
}

async function collectDroppedEntry(entry, parentPath, output) {
  const path = parentPath ? `${parentPath}/${entry.name}` : entry.name;
  if (entry.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
    output.push({ file, relativePath: path });
    return;
  }
  if (!entry.isDirectory) return;
  for (const child of await readDroppedDirectory(entry)) {
    await collectDroppedEntry(child, path, output);
  }
}

async function collectDroppedHostFiles(dataTransfer) {
  const entries = [...(dataTransfer.items || [])]
    .filter(item => item.kind === "file")
    .map(item => item.webkitGetAsEntry?.())
    .filter(Boolean);
  if (entries.some(entry => entry.isDirectory)) {
    const output = [];
    for (const entry of entries) await collectDroppedEntry(entry, "", output);
    return output;
  }
  return hostFolderRecords([...dataTransfer.files]);
}

async function prepareHostFolderMetadata(records) {
  const sidecars = new Map();
  for (const item of records.filter(row => /\.inf$/i.test(row.relativePath))) {
    const key = item.relativePath.replace(/\.inf$/i, "").toLowerCase();
    const fields = (await item.file.text()).trim().match(/"[^"]*"|\S+/g) || [];
    // name attributes length [datestamp] -- the record this application
    // writes beside an exported file, and the only metadata GEMDOS keeps.
    sidecars.set(key, {
      targetName: String(fields[0] || "").replace(/^"|"$/g, "").split(/[\\/]/).at(-1),
      attributes: normaliseAttributes(fields[1]),
      datestamp: String(fields[3] || "").replace(/^"|"$/g, ""),
    });
  }
  return records.filter(item => !/\.inf$/i.test(item.relativePath)).map(item => ({
    ...item,
    metadata: { ...(sidecars.get(item.relativePath.toLowerCase()) || {}) },
  }));
}

async function reviewHostImport(index, records, operation, itemType = "file") {
  try {
    const report = await requestCompatibilityReport(
      index,
      operation,
      "host",
      records.map(item => ({
        name: itemType === "disk image"
          ? formats.stem(item.file?.name || item.relativePath || "DISK")
          : item.metadata?.targetName || item.file?.name || item.relativePath || "FILE",
        nameIsLeaf: true,
        parent: String(item.relativePath || "").replace(/\\/g, "/").split("/").slice(0, -1).join("/"),
        source: item.relativePath || item.file?.name || "Local file",
        type: itemType,
        allowDuplicateName: panes[index].image.kind === "hd" && panes[index].partition === null,
        attributes: item.metadata?.attributes || "",
        datestamp: item.metadata?.datestamp || "",
        filetype: item.metadata?.filetype || "",
      })),
    );
    return reviewCompatibilityReport(index, report, {
      heading: `Import into ${panes[index].image.name}`,
      continueLabel: `Continue with ${records.length} item${records.length === 1 ? "" : "s"}`,
    });
  } catch (error) {
    toast(error.message, true);
    return false;
  }
}

async function addSelectedHostFolder(index, records) {
  const pane = panes[index];
  if (!records.length || !pane.image) return;
  if (pane.image.kind === "rom") {
    const relevant = records.filter(item => !ignoredFolderFile(item.relativePath));
    return addRomHostFiles(index, relevant.map(item => item.file));
  }
  const reviewedRecords = await prepareHostFolderMetadata(records);
  const relevant = reviewedRecords.filter(item => !ignoredFolderFile(item.relativePath));
  const ignoredCount = records.length - relevant.length;
  if (!relevant.length) {
    return toast("That folder contains no importable files.", true);
  }
  if (!await reviewHostImport(
    index,
    relevant,
    "file-menu-folder-import",
    "file",
  )) return false;
  const canPreserve = paneHoldsVolume(pane);
  const initialMode = canPreserve ? "preserve" : "flatten";
  const roots = new Set(relevant.map(item => item.relativePath.replace(/\\/g, "/").split("/")[0]));
  const initial = folderTargetPlans(pane, relevant, initialMode);
  const closed = showModal(`
    <h2>Import ${roots.size} folder${roots.size === 1 ? "" : "s"}</h2>
    <p>${relevant.length} file${relevant.length === 1 ? "" : "s"} will be imported into <code>${esc(drivePath(pane.partitionName || pane.image.driveLetter || "", pane.path))}</code>. Review how host folders should map to the target filing system.</p>
    ${canPreserve ? `<div class="install-modes">
      <label class="check-field install-mode"><input type="radio" name="folderMode" value="preserve" checked><span><b>Preserve folder structure</b><small>Create the selected folder tree under the current GEMDOS folder.</small></span></label>
      <label class="check-field install-mode"><input type="radio" name="folderMode" value="flatten"><span><b>Import all files here</b><small>Ignore host folders and place every file in the current folder.</small></span></label>
    </div>` : `<input type="hidden" name="folderMode" value="flatten"><div class="help-note">This view has no folders of its own. Files from all selected folders will be imported into <strong>${esc(pane.path || "the root")}</strong>.</div>`}
    <div class="folder-import-preview" data-folder-preview>${initial.plans.slice(0, 12).map(item => `<code>${esc(item.relativePath)} → ${esc(item.targetPath)}</code>`).join("")}</div>
    ${ignoredCount ? `<div class="help-note">${ignoredCount} metadata sidecar or operating-system housekeeping file${ignoredCount === 1 ? "" : "s"} will not be stored as a separate file.</div>` : ""}
    <label class="check-field"><input type="checkbox" name="replace" value="yes"> Replace ordinary files that already have the same target path</label>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="import">Import ${relevant.length} file${relevant.length === 1 ? "" : "s"}</button></div>`,
  async formValues => {
    const mode = String(formValues.get("folderMode") || initialMode);
    const plan = folderTargetPlans(pane, relevant, mode);
    const form = new FormData();
    plan.plans.forEach(item => form.append("files", item.file));
    form.append("targetPaths", JSON.stringify(plan.plans.map(item => item.targetPath)));
    form.append("metadata", JSON.stringify(plan.plans.map(item => item.metadata || {})));
    form.append("destination", pane.path);
    form.append("mode", mode);
    form.append("replace", formValues.get("replace") === "yes" ? "true" : "false");
    if (pane.partition !== null) form.append("partition", pane.partition);
    if (pane.side !== null) form.append("side", pane.side);
    const data = await paneOperation(index, `Importing ${relevant.length} folder file${relevant.length === 1 ? "" : "s"}…`, () =>
      api(`/api/images/${pane.image.id}/folder-import`, { method: "POST", body: form }));
    if (data.conflicts?.length) {
      throw new Error(`${data.conflicts.length} target file${data.conflicts.length === 1 ? " already exists" : "s already exist"}. Tick “Replace ordinary files” to overwrite: ${data.conflicts.slice(0, 4).join(", ")}${data.conflicts.length > 4 ? "…" : ""}`);
    }
    pane.image = data.image;
    await loadDirectory(index);
    toast(`${data.imported.length} file${data.imported.length === 1 ? "" : "s"} imported`);
  });
  if (canPreserve) {
    modalContent.querySelectorAll('input[name="folderMode"]').forEach(input => {
      input.onchange = () => {
        const plan = folderTargetPlans(pane, relevant, input.value);
        modalContent.querySelector("[data-folder-preview]").innerHTML = plan.plans.slice(0, 12)
          .map(item => `<code>${esc(item.relativePath)} → ${esc(item.targetPath)}</code>`).join("");
      };
    });
  }
  return closed;
}

async function addSelectedHostFiles(index, files) {
  if (!files.length) return;
  const pane = panes[index];
  if (pane.image?.kind === "rom") return addRomHostFiles(index, files);
  const preparedFiles = await prepareHostFileMetadata(files);
  if (!preparedFiles.length) return toast("The selection contained metadata sidecars but no data files.", true);
  // An importable floppy container has its own installation planner. It must
  // inspect the container before it can describe the real operation: extract
  // its contents, choose a destination and optional child folder, or retain
  // the source image as an ordinary file. Running the generic file preflight
  // first treats the container name as a GEMDOS leaf name and hides that
  // decision behind an irrelevant filename warning.
  const ordinaryFiles = paneHoldsVolume(pane)
    ? preparedFiles.filter(item => !formats.isImportableImage(item.file.name))
    : preparedFiles;
  if (ordinaryFiles.length
    && !await reviewHostImport(
      index,
      ordinaryFiles,
      "file-menu-file-import",
      "file",
    )) return false;
  const batch = { current: 0, total: preparedFiles.length, acceptAll: false, currentMetadata: null };
  pane.actionPending = true;
  renderPane(index);
  try {
    for (const [offset, item] of preparedFiles.entries()) {
      batch.current = offset + 1;
      batch.currentMetadata = item.metadata;
      await importHostFile(index, item.file, false, batch);
      // A raw-image choice replaces its extraction dialog on the next task.
      // Give that replacement time to open and wait for it as part of the
      // current file before moving on to the next selection.
      await new Promise(resolve => setTimeout(resolve, 0));
      if (modal.open) {
        await new Promise(resolve => {
          modal.addEventListener("close", resolve, { once: true });
        });
      }
    }
  } finally {
    if (panes[index] === pane) {
      pane.actionPending = false;
      renderPane(index);
    }
  }
}

async function addRomHostFiles(index, files, firstBank = null) {
  const pane = panes[index];
  const bankSize = Number(pane.image.rom?.bankSize || 16384);
  const expanded = [];
  for (const file of files) {
    if (!file.size) continue;
    if (file.size <= bankSize) {
      expanded.push({ file, offset: 0, name: file.name });
      continue;
    }
    if (file.size % bankSize) {
      toast(`${file.name} is ${humanSize(file.size)} and is not a whole number of ${humanSize(bankSize)} banks. Change the ROM layout or split it explicitly.`, true);
      return false;
    }
    const bytes = await file.arrayBuffer();
    for (let offset = 0; offset < file.size; offset += bankSize) {
      expanded.push({
        file: new File([bytes.slice(offset, offset + bankSize)], `${formats.stem(file.name)}-bank-${String(offset / bankSize).padStart(3, "0")}.rom`, { type: "application/octet-stream" }),
        offset,
        name: file.name,
      });
    }
  }
  if (!expanded.length) return toast("No ROM bytes were selected.", true);
  return showModal(`
    <h2>Add ${expanded.length} ROM bank${expanded.length === 1 ? "" : "s"}</h2>
    <p>Each input is fitted to a ${humanSize(bankSize)} bank and padded with &${Number(pane.image.rom?.eraseByte ?? 255).toString(16).toUpperCase().padStart(2, "0")}. Larger, exact-multiple images are split in file order.</p>
    <div class="field"><label>First destination</label><select name="placement">
      <option value="empty" ${firstBank == null ? "selected" : ""}>First empty banks, then append</option>
      <option value="bank" ${firstBank != null ? "selected" : ""}>Bank ${firstBank ?? 0}, then consecutive banks</option>
      <option value="append">Append after the current image</option>
    </select></div>
    <div class="help-note"><strong>Existing bytes:</strong> choosing a numbered bank can overwrite populated banks. Atari File Forge creates an undo checkpoint first.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="add">Add banks</button></div>`,
  async form => {
    const placement = form.get("placement");
    const start = placement === "append" ? Number(pane.image.rom?.bankCount || 0) : placement === "bank" ? Number(firstBank ?? 0) : null;
    for (const [offset, item] of expanded.entries()) {
      const body = new FormData();
      body.append("file", item.file);
      if (start != null) body.append("bank", start + offset);
      const data = await paneOperation(index, `Adding ROM bank ${offset + 1} of ${expanded.length}…`, () => api(`/api/images/${pane.image.id}/files`, { method: "POST", body }));
      pane.image = data.image;
    }
    await loadDirectory(index);
    toast(`${expanded.length} ROM bank${expanded.length === 1 ? "" : "s"} added`);
    return true;
  });
}

async function appendBlankRomBank(index) {
  const pane = panes[index];
  const data = await paneOperation(index, "Appending an empty ROM bank…", () => api(`/api/images/${pane.image.id}/rom-banks/blank`, { method: "POST" }));
  pane.image = data.image;
  await loadDirectory(index);
  setSelection(pane, [String(data.bank)], String(data.bank));
  renderPane(index, true);
  toast(`Empty ROM bank ${data.bank} appended`);
}

function configureRomLayout(index) {
  const pane = panes[index];
  const rom = pane.image.rom || {};
  showModal(`
    <h2>ROM layout</h2>
    <p>These settings change how the existing bytes are divided and described. They do not reorder or rewrite the image.</p>
    <div class="field"><label>Target family</label><select name="platform">
      <option value="tos" ${rom.platform === "tos" ? "selected" : ""}>TOS ROM · 192 KiB, 256 KiB or 512 KiB</option>
      <option value="cartridge" ${rom.platform === "cartridge" ? "selected" : ""}>Cartridge · 128 KiB at &amp;FA0000</option>
      <option value="custom" ${rom.platform === "custom" ? "selected" : ""}>Custom expansion or diagnostic ROM</option>
    </select></div>
    <div class="field"><label>Bank size in bytes</label><input name="bankSize" type="number" min="256" max="67108864" step="256" value="${Number(rom.bankSize || 16384)}" required><small>262,144 is a 256 KiB TOS 1.04 or 2.06 ROM and 524,288 a 512 KiB TOS 3.06. A 128 KiB cartridge is 131,072.</small></div>
    <div class="field"><label>Erased byte</label><select name="eraseByte"><option value="255" ${Number(rom.eraseByte) !== 0 ? "selected" : ""}>&FF</option><option value="0" ${Number(rom.eraseByte) === 0 ? "selected" : ""}>&00</option></select></div>
    <div class="field"><label>Byte layout</label><select name="layout">
      <option value="linear" ${rom.layout === "linear" ? "selected" : ""}>Linear / banked bytes</option>
      <option value="byte-interleaved-2" ${rom.layout === "byte-interleaved-2" ? "selected" : ""}>Two byte-wide chips, interleaved</option>
      <option value="byte-interleaved-4" ${rom.layout === "byte-interleaved-4" ? "selected" : ""}>Four byte-wide chips, interleaved</option>
    </select><small>The image remains byte-for-byte unchanged. The setting documents how it is wired and controls future component exports.</small></div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="apply">Apply layout</button></div>`,
  async form => {
    const data = await api(`/api/images/${pane.image.id}/rom-layout`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(form)),
    });
    pane.image = data.image;
    await loadDirectory(index);
    toast("ROM layout updated; image bytes were not changed");
  });
}

async function showRomWorkbench(index, initial = {}) {
  const pane = panes[index];
  if (pane?.image?.kind !== "rom") return;
  const imageId = pane.image.id;
  const [mapping, identity, audit, emulator] = await paneOperation(index, "Analysing ROM structure…", () => Promise.all([
    api(`/api/images/${imageId}/rom/map`),
    api(`/api/images/${imageId}/rom/identify`),
    api(`/api/images/${imageId}/rom/audit`),
    api(`/api/images/${imageId}/rom/emulator`),
  ]));
  const otherRoms = panes.map((item, paneIndex) => ({ item, paneIndex })).filter(row => row.paneIndex !== index && row.item.image?.kind === "rom");
  const project = pane.image.rom?.project || {};
  const bankOptions = mapping.banks.map(row => `<option value="${row.bank}">Bank ${row.bank} · ${esc(row.title)}</option>`).join("");
  const findings = audit.findings.length ? audit.findings.map(row => `<li class="${esc(row.level)}">${row.bank == null ? "" : `Bank ${row.bank}: `}${esc(row.message)}</li>`).join("") : "<li>No structural faults were found.</li>";
  const mapRows = mapping.banks.map(row => `<tr><td>${row.bank}</td><td><code>&amp;${Number(row.fileOffset).toString(16).toUpperCase().padStart(6, "0")}</code></td><td>${esc(row.title)}</td><td>${esc(row.type)}</td><td>${row.duplicates.length ? row.duplicates.join(", ") : ""}</td></tr>`).join("");
  showModal(`<div class="rom-workbench">
    <div class="modal-heading"><span class="modal-kicker">ROM MAINTENANCE AND DEVELOPMENT</span><h2>ROM Workbench · ${esc(pane.image.name)}</h2><p>Analyse code, compare revisions, prepare programmer files and retain project notes without treating ROM bytes as a filing system.</p></div>
    <nav class="rom-workbench-tabs" role="tablist" aria-label="ROM Workbench sections">
      ${[["overview","Overview"],["code","Disassembly"],["compare","Compare"],["build","Build"],["export","Programmer"],["project","Project"],["test","Emulator"]].map(([key,label], position) => `<button type="button" role="tab" id="rom-tab-${key}" aria-controls="rom-panel-${key}" aria-selected="${position ? "false" : "true"}" tabindex="${position ? "-1" : "0"}" data-rom-tab="${key}" class="${position ? "" : "active"}">${label}</button>`).join("")}
    </nav>
    <section role="tabpanel" id="rom-panel-overview" aria-labelledby="rom-tab-overview" data-rom-panel="overview" class="rom-workbench-panel active">
      <div class="operation-summary"><span><b>${mapping.bankCount}</b><small>Banks</small></span><span><b>${humanSize(mapping.bankSize)}</b><small>Bank size</small></span><span><b>${identity.matched ? esc(identity.record?.title || "Known") : "Unknown"}</b><small>Catalogue identity</small></span><span><b>${audit.healthy ? "Pass" : "Review"}</b><small>Health</small></span></div>
      ${identity.transformations.map(message => `<div class="help-note">${esc(message)}</div>`).join("")}
      <div class="rom-map-table"><table><thead><tr><th>Bank</th><th>File offset</th><th>Title</th><th>Type</th><th>Duplicates</th></tr></thead><tbody>${mapRows}</tbody></table></div>
      <h3>Audit findings</h3><ul class="rom-audit-findings">${findings}</ul>
      ${audit.repairable.includes("extension-checksum") ? '<button type="button" class="button danger repair-rom-checksum" data-repair="extension-checksum">Repair extension-ROM checksum…</button>' : ""}
      ${audit.repairable.includes("header-role-flags") ? '<button type="button" class="button danger repair-rom-checksum" data-repair="header-role-flags">Align header role flags with entry vectors…</button>' : ""}
      <details class="rom-identity-editor"><summary>Identify this exact ROM</summary><div class="rom-identity-grid"><label>Title<input name="identityTitle" value="${esc(identity.record?.title || project.identity?.title || "")}"></label><label>Version<input name="identityVersion" value="${esc(identity.record?.version || project.identity?.version || "")}"></label><label>Publisher<input name="identityPublisher" value="${esc(identity.record?.publisher || project.identity?.publisher || "")}"></label><label>Platform<input name="identityPlatform" value="${esc(identity.record?.platform || project.identity?.platform || "")}"></label></div><div class="field"><label>Identification notes</label><textarea name="identityNotes" rows="3">${esc(identity.record?.notes || project.identity?.notes || "")}</textarea></div><button type="button" class="button primary save-rom-identity">Save fingerprinted identity</button><small>This browser owner's catalogue keys the record to the complete SHA-256, not the filename.</small></details>
    </section>
    <section role="tabpanel" id="rom-panel-code" aria-labelledby="rom-tab-code" data-rom-panel="code" class="rom-workbench-panel" hidden>
      <div class="rom-tool-controls"><label>Bank<select name="disasmBank">${bankOptions}</select></label><label>Architecture<select name="disasmArchitecture"><option value="auto">Auto detect</option><option value="68000">MC68000 · ST, Mega ST, STE, Mega STE</option><option value="68010">MC68010</option><option value="68020">MC68020</option><option value="68030">MC68030 · TT030, Falcon030</option><option value="68040">MC68040</option><option value="68060">MC68060</option></select></label><label>Mapped origin<input name="disasmOrigin" value="0xE00000"></label><label>Offset<input name="disasmOffset" value="0x0"></label><label>Bytes<input name="disasmLength" type="number" min="1" max="262144" value="4096"></label><button type="button" class="button primary run-disassembly">Disassemble</button></div>
      <div class="help-note">Every 68000-family processor is decoded big-endian, which is the only byte order an Atari uses. GEMDOS, BIOS, XBIOS, AES and VDI traps are named, hardware registers and exception vectors are identified, known entry points seed reachable-code analysis, branch and call targets gain cross-references, and bytes that are not valid instructions stay as data.</div>
      <div class="rom-disassembly-output empty-list">Choose a bank and start address.</div>
    </section>
    <section role="tabpanel" id="rom-panel-compare" aria-labelledby="rom-tab-compare" data-rom-panel="compare" class="rom-workbench-panel" hidden>
      ${otherRoms.length ? `<div class="rom-tool-controls"><label>Compare with<select name="compareImage">${otherRoms.map(row => `<option value="${esc(row.item.image.id)}">Pane ${row.paneIndex + 1} · ${esc(row.item.image.name)}</option>`).join("")}</select></label><button type="button" class="button primary compare-rom">Compare images</button></div>` : '<div class="help-note">Open another ROM in a second pane to compare it with this image.</div>'}
      <div class="rom-compare-output"></div>
      <hr><label class="field"><span>Apply Atari File Forge patch</span><input class="rom-patch-file" type="file" accept="application/json,.json,.affpatch"></label><button type="button" class="button danger apply-rom-patch" disabled>Apply checksum-verified patch…</button>
    </section>
    <section role="tabpanel" id="rom-panel-build" aria-labelledby="rom-tab-build" data-rom-panel="build" class="rom-workbench-panel" hidden>
      <div class="help-warning"><strong>This replaces the working ROM bytes.</strong> An automatic undo checkpoint is created. Generated handlers are inert until ROM code is supplied.</div>
      <div class="field"><label>Template</label><select name="builderTemplate"><option value="service">Cartridge scaffold with an application header</option><option value="data-archive">Cartridge file archive</option></select></div>
      <div class="field"><label>ROM title</label><input name="builderTitle" maxlength="24" value="${esc(pathNameWithoutExtension(pane.image.name) || "NEW ROM")}"></div>
      <div class="field"><label>Size</label><select name="builderSize"><option value="8192">8 KiB</option><option value="16384" selected>16 KiB</option><option value="32768">32 KiB</option></select></div>
      <div class="field"><label>Application names, one per line</label><textarea name="builderCommands" rows="5" placeholder="DISK MENU&#10;GAME MENU"></textarea></div>
      <div class="field rom-archive-files" hidden><label>Files for the data archive</label><input name="builderFiles" type="file" multiple><small>The archive needs its companion cartridge application; TOS does not read an unrecognised cartridge on its own.</small></div>
      <button type="button" class="button danger build-rom">Build and replace working ROM…</button>
    </section>
    <section role="tabpanel" id="rom-panel-export" aria-labelledby="rom-tab-export" data-rom-panel="export" class="rom-workbench-panel" hidden>
      <div class="field"><label>Physical device size in bytes</label><input name="deviceSize" type="number" min="${pane.image.size}" max="67108864" step="1" value="${2 ** Math.ceil(Math.log2(Math.max(1, pane.image.size)))}"></div>
      <div class="field"><label>Physical byte lanes</label><select name="exportLanes"><option value="1">One chip</option><option value="2">Two byte-wide chips</option><option value="4">Four byte-wide chips</option></select></div>
      <label class="check-line"><input name="exportMirror" type="checkbox"> Mirror the image to fill the device</label><label class="check-line"><input name="exportSwap" type="checkbox"> Swap each adjacent byte pair</label><label class="check-line"><input name="exportWordSwap" type="checkbox"> Swap 16-bit words within each 32-bit group</label>
      <div class="field"><label>Address-line swaps</label><input name="exportAddressSwaps" placeholder="0:1, 2:3"><small>Optional physical rewiring, written as address-bit pairs. For example, <code>0:1</code> swaps A0 and A1.</small></div>
      <div class="help-warning">Review the ZIP programming report and verify the exported checksum before writing physical hardware.</div><button type="button" class="button primary export-rom">Build programmer ZIP</button>
    </section>
    <section role="tabpanel" id="rom-panel-project" aria-labelledby="rom-tab-project" data-rom-panel="project" class="rom-workbench-panel" hidden>
      <div class="field"><label>Hardware and socket notes</label><input name="projectHardware" value="${esc(project.hardware || "")}"></div><div class="field"><label>Project notes</label><textarea name="projectNotes" rows="6">${esc(project.notes || "")}</textarea></div><div class="field"><label>Symbols as address = label</label><textarea name="projectSymbols" rows="6">${esc(Object.entries(project.symbols || {}).map(([address,label]) => `${address} = ${label}`).join("\n"))}</textarea></div><div class="field"><label>Known regions as start-end = meaning</label><textarea name="projectRegions" rows="6">${esc((project.regions || []).map(row => `${row.start}-${row.end} = ${row.name}`).join("\n"))}</textarea></div><button type="button" class="button primary save-rom-project">Save project metadata</button>
    </section>
    <section role="tabpanel" id="rom-panel-test" aria-labelledby="rom-tab-test" data-rom-panel="test" class="rom-workbench-panel" hidden><div class="${emulator.available ? "help-note" : "help-warning"}">${esc(emulator.message)}</div><button type="button" class="button primary run-rom-emulator" ${emulator.available ? "" : "disabled"}>Run configured emulator test</button><pre class="rom-emulator-output"></pre></section>
    <div class="modal-actions"><button class="button primary" value="cancel">Close workbench</button></div>
  </div>`);

  const root = modalContent.querySelector(".rom-workbench");
  const activate = name => {
    root.querySelectorAll("[data-rom-tab]").forEach(button => { const active=button.dataset.romTab === name; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); button.tabIndex=active?0:-1; });
    root.querySelectorAll("[data-rom-panel]").forEach(panel => { const active=panel.dataset.romPanel === name; panel.classList.toggle("active", active); panel.hidden=!active; });
  };
  root.querySelectorAll("[data-rom-tab]").forEach(button => button.onclick = () => activate(button.dataset.romTab));
  root.querySelector('[name="builderTemplate"]').onchange = event => root.querySelector(".rom-archive-files").hidden = event.target.value !== "data-archive";
  root.querySelector(".run-disassembly").onclick = async () => {
    const bank = root.querySelector('[name="disasmBank"]').value;
    const architecture = root.querySelector('[name="disasmArchitecture"]').value;
    const origin = root.querySelector('[name="disasmOrigin"]').value || "0xF80000";
    const offset = root.querySelector('[name="disasmOffset"]').value || "0";
    const length = root.querySelector('[name="disasmLength"]').value || "4096";
    const report = await api(`/api/images/${imageId}/rom/disassembly?bank=${encodeURIComponent(bank)}&architecture=${encodeURIComponent(architecture)}&origin=${encodeURIComponent(origin)}&offset=${encodeURIComponent(offset)}&length=${encodeURIComponent(length)}`);
    const output=root.querySelector(".rom-disassembly-output");
    output.innerHTML = `<div class="operation-summary"><span><b>${esc(report.architecture.toUpperCase())}</b><small>Architecture</small></span><span><b>${report.rows.length}</b><small>Decoded instructions</small></span><span><b>${report.reachableInstructions}</b><small>Reachable</small></span><span><b>${report.crossReferences.length}</b><small>Referenced targets</small></span></div><table><thead><tr><th>Address</th><th>Bytes</th><th>Instruction</th><th>References</th><th>Comment</th></tr></thead><tbody>${report.rows.map(row => `<tr class="${row.reachable ? "reachable" : "unreached"}"><td><code>&amp;${Number(row.address).toString(16).toUpperCase().padStart(4,"0")}</code></td><td><code>${row.bytes}</code></td><td><code>${row.label ? `${esc(row.label)}: ` : ""}${row.mnemonic} ${esc(row.operand)}</code></td><td>${row.references?.length ? row.references.map(value=>`&amp;${Number(value).toString(16).toUpperCase()}`).join(", ") : ""}</td><td>${esc(row.comment)}</td></tr>`).join("")}</tbody></table>`;
    output.scrollTop=0;
    output.scrollLeft=0;
  };
  root.querySelector('[name="disasmArchitecture"]').onchange = event => {
    // TOS is decoded at $E00000 on every machine that has it in ROM; a
    // cartridge lives at $FA0000, so the origin follows the kind of ROM
    // rather than the processor.
    if (event.target.value !== "auto") root.querySelector('[name="disasmOrigin"]').value = "0xE00000";
    else if (root.querySelector('[name="disasmOrigin"]').value === "0x0") root.querySelector('[name="disasmOrigin"]').value = "0xFA0000";
  };
  root.querySelector(".compare-rom")?.addEventListener("click", async () => {
    const report = await api(`/api/images/${imageId}/rom/compare`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({targetImage: root.querySelector('[name="compareImage"]').value, includePatch: true}) });
    root.querySelector(".rom-compare-output").innerHTML = `<div class="operation-summary"><span><b>${report.changedBytes}</b><small>Changed bytes</small></span><span><b>${report.ranges.length}${report.rangesTruncated?"+":""}</b><small>Changed ranges</small></span></div>${report.patch?'<button type="button" class="button ghost download-rom-patch">Download all as guarded patch</button><button type="button" class="button ghost download-selected-rom-patch">Download selected ranges</button>':`<div class="help-warning">${esc(report.patchUnavailable||"This comparison is too large for a safe patch file.")}</div>`}<div class="rom-map-table"><table><thead><tr><th><span class="sr-only">Select</span></th><th>Start</th><th>End</th><th>Length</th></tr></thead><tbody>${report.ranges.slice(0,500).map((row,rangeIndex) => `<tr><td><input type="checkbox" class="rom-range-choice" value="${rangeIndex}" aria-label="Select changed range ${rangeIndex+1}"></td><td>&amp;${row.start.toString(16).toUpperCase()}</td><td>&amp;${row.end.toString(16).toUpperCase()}</td><td>${row.length}</td></tr>`).join("")}</tbody></table></div>`;
    root.querySelector(".download-rom-patch")?.addEventListener("click", () => downloadDocument(`${pathNameWithoutExtension(report.leftName)}-to-${pathNameWithoutExtension(report.rightName)}.affpatch`, JSON.stringify(report.patch, null, 2)));
    root.querySelector(".download-selected-rom-patch")?.addEventListener("click", async () => { const rangeIndexes=[...root.querySelectorAll(".rom-range-choice:checked")].map(input=>Number(input.value)); if(!rangeIndexes.length)return toast("Select at least one changed range.",true); const selected=await api(`/api/images/${imageId}/rom/compare`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({targetImage:root.querySelector('[name="compareImage"]').value,includePatch:true,rangeIndexes})}); if(!selected.patch)return toast(selected.patchUnavailable||"Could not build that selective patch.",true); downloadDocument(`${pathNameWithoutExtension(report.leftName)}-selected-changes.affpatch`,JSON.stringify(selected.patch,null,2)); });
  });
  let patchDocument = null;
  root.querySelector(".rom-patch-file").onchange = async event => { try { patchDocument = JSON.parse(await event.target.files[0].text()); root.querySelector(".apply-rom-patch").disabled = false; } catch (error) { patchDocument = null; toast(`Could not read patch: ${error.message}`, true); } };
  root.querySelector(".apply-rom-patch").onclick = async () => {
    if (!patchDocument || !await confirmChoice("Apply this ROM patch?", "This changes raw ROM bytes and may make hardware unbootable.", { confirmLabel: "Apply verified patch", danger: true, note: "The patch has been checksum-verified against this exact image." })) return;
    const data = await api(`/api/images/${imageId}/rom/patch`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({patch:patchDocument})}); pane.image=data.image; modal.close(); await loadDirectory(index); toast("ROM patch applied and verified");
  };
  root.querySelectorAll(".repair-rom-checksum").forEach(button => button.addEventListener("click", async () => { const action=button.dataset.repair; if (!await confirmChoice("Repair this ROM metadata fault?", "The fault has been proven against this image.", { confirmLabel: "Repair", note: "An undo checkpoint is created first." })) return; const data=await api(`/api/images/${imageId}/rom/repair`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action})}); pane.image=data.image; modal.close(); await loadDirectory(index); toast("ROM metadata repaired and re-audited"); }));
  root.querySelector(".build-rom").onclick = async () => {
    if (!await confirmChoice("Replace every byte in this ROM?", "The complete working ROM is overwritten with the generated image.", { confirmLabel: "Replace the ROM", danger: true, note: "An undo checkpoint is created first." })) return;
    const commands = root.querySelector('[name="builderCommands"]').value.split(/\n/).map(line => line.trim()).filter(Boolean).map(line => { const [name,...syntax]=line.split(/\s+/); return {name,syntax:syntax.join(" ")}; });
    const files = [];
    for (const file of root.querySelector('[name="builderFiles"]').files) files.push({name:file.name,hex:[...new Uint8Array(await file.arrayBuffer())].map(value=>value.toString(16).padStart(2,"0")).join("")});
    const body={template:root.querySelector('[name="builderTemplate"]').value,title:root.querySelector('[name="builderTitle"]').value,size:Number(root.querySelector('[name="builderSize"]').value),commands,files};
    const data=await api(`/api/images/${imageId}/rom/build`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); pane.image=data.image; modal.close(); await loadDirectory(index); toast("ROM scaffold built; handlers remain inert until code is supplied");
  };
  root.querySelector(".export-rom").onclick = async () => {
    const swaps=root.querySelector('[name="exportAddressSwaps"]').value.split(",").map(value=>value.trim()).filter(Boolean).map(value=>value.split(":").map(Number));
    const response=await fetch(`/api/images/${imageId}/rom/hardware-export`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({deviceSize:Number(root.querySelector('[name="deviceSize"]').value),lanes:Number(root.querySelector('[name="exportLanes"]').value),mirror:root.querySelector('[name="exportMirror"]').checked,byteSwap:root.querySelector('[name="exportSwap"]').checked,wordSwap:root.querySelector('[name="exportWordSwap"]').checked,addressSwaps:swaps})}); if(!response.ok){const row=await response.json();throw new Error(row.error||"Export failed");} const blob=await response.blob(); const url=URL.createObjectURL(blob); const link=document.createElement("a");link.href=url;link.download=`${pathNameWithoutExtension(pane.image.name)}-programmer.zip`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  root.querySelector(".save-rom-project").onclick = async () => { const symbols={}; root.querySelector('[name="projectSymbols"]').value.split(/\n/).forEach(line=>{const split=line.indexOf("=");if(split>0)symbols[line.slice(0,split).trim()]=line.slice(split+1).trim();}); const regions=[]; root.querySelector('[name="projectRegions"]').value.split(/\n/).forEach(line=>{const match=line.match(/^\s*([^\s-]+)\s*-\s*([^\s=]+)\s*=\s*(.+)$/);if(match)regions.push({start:match[1],end:match[2],name:match[3].trim()});}); const data=await api(`/api/images/${imageId}/rom/project`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({...project,hardware:root.querySelector('[name="projectHardware"]').value,notes:root.querySelector('[name="projectNotes"]').value,symbols,regions})});pane.image=data.image;toast("ROM project metadata saved"); };
  root.querySelector(".save-rom-identity").onclick = async () => { const body={title:root.querySelector('[name="identityTitle"]').value,version:root.querySelector('[name="identityVersion"]').value,publisher:root.querySelector('[name="identityPublisher"]').value,platform:root.querySelector('[name="identityPlatform"]').value,notes:root.querySelector('[name="identityNotes"]').value};const data=await api(`/api/images/${imageId}/rom/identity`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});pane.image=data.image;toast("ROM identity saved against its exact fingerprint"); };
  root.querySelector(".run-rom-emulator").onclick = async () => { const data=await api(`/api/images/${imageId}/rom/emulator`,{method:"POST"});root.querySelector(".rom-emulator-output").textContent=`Exit ${data.result.returnCode}\n${data.result.stdout}\n${data.result.stderr}`; };
  if (initial.tab) activate(initial.tab);
  if (initial.tab === "code" && initial.address != null) {
    const rawAddress = String(initial.address).trim().replace(/^&/, "0x");
    const address = Number(rawAddress);
    if (Number.isFinite(address)) {
      root.querySelector('[name="disasmBank"]').value = String(initial.bank ?? 0);
      root.querySelector('[name="disasmOffset"]').value = `0x${Math.max(0, address >= 0xE00000 ? address - 0xE00000 : address >= 0xFA0000 ? address - 0xFA0000 : address).toString(16).toUpperCase()}`;
      root.querySelector(".run-disassembly").click();
    }
  }
}

async function prepareHostFileMetadata(files) {
  const sidecars = new Map();
  for (const file of files.filter(item => /\.inf$/i.test(item.name))) {
    const key = file.name.replace(/\.inf$/i, "").toLowerCase();
    const fields = (await file.text()).trim().match(/"[^"]*"|\S+/g) || [];
    const storedName = String(fields[0] || "").replace(/^"|"$/g, "").split(/[\\/]/).at(-1);
    sidecars.set(key, {
      targetName: storedName || file.name.replace(/\.inf$/i, ""),
      attributes: normaliseAttributes(fields[1]),
      datestamp: String(fields[3] || "").replace(/^"|"$/g, ""),
    });
  }
  return files.filter(file => !/\.inf$/i.test(file.name)).map(file => ({
    file,
    metadata: { ...(sidecars.get(file.name.toLowerCase()) || {}) },
  }));
}

async function importHostFile(index, file, forceRaw = false, batch = null) {
  const pane = panes[index];
  if (!pane.image || (pane.image.kind === "hd" && pane.partition === null)) return toast("Open a volume first.", true);
  if (!forceRaw && paneHoldsVolume(pane) && formats.isImportableImage(file.name)) {
    return promptImageExtraction(index, file, batch);
  }
  const detected = batch?.currentMetadata || {};
  const nameRule = targetNameRule(pane, detected.targetName || file.name);
  if (batch?.acceptAll) {
    return addHostFileWithPlan(index, file, {
      targetName: nameRule.suggested,
      attributes: detected.attributes,
      datestamp: detected.datestamp,
      filetype: detected.filetype,
    });
  }
  const batchLabel = batch?.total > 1
    ? `<p class="batch-position">Selected file ${batch.current} of ${batch.total}</p>`
    : "";
  const canApplyAll = batch?.total > batch?.current;
  const closed = showModal(`
    <h2>Insert ${esc(file.name)}</h2>${batchLabel}<p>${nameRule.valid ? "Choose the target filename and optional GEMDOS metadata." : `${esc(file.name)} is not a legal ${nameRule.label} filename, so a safe replacement has been suggested.`}</p>
    <div class="field"><label>Target filename</label>
      <input name="targetName" maxlength="${nameRule.limit}" value="${esc(nameRule.suggested)}" required>
      <small>Up to ${nameRule.limit} characters, in ${esc(nameRule.label)} spelling.</small></div>
    <div class="field"><label>Attributes</label>
      <input name="attributes" value="${esc(detected.attributes || "")}" placeholder="-----a" maxlength="6">
      <small>The six letters <code>rhsvda</code>. Leave it empty for an ordinary <code>-----a</code>.</small></div>
    <div class="field"><label>Datestamp</label>
      <input name="datestamp" type="datetime-local" step="2" value="${esc(String(detected.datestamp || "").slice(0, 19).replace(" ", "T"))}">
      <small>Leave it empty to stamp the file with the time it is written.</small></div>
    <div class="field"><label>Desktop icon type</label>
      <input name="filetype" placeholder="GEM, TOS or TTP">
      <small>Only when the desktop should be told how to start the file.</small></div>
    <input type="hidden" name="applyRemaining" value="no">
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button>${canApplyAll ? '<button class="button ghost apply-import-all" value="add">Insert and apply to all remaining</button>' : ""}<button class="button primary" value="add">Insert File</button></div>`,
  async formValues => {
    const plan = Object.fromEntries(["targetName", "attributes", "datestamp", "filetype"]
      .map(key => [key, formValues.get(key)]));
    if (batch && formValues.get("applyRemaining") === "yes") {
      batch.acceptAll = true;
    }
    return addHostFileWithPlan(index, file, plan);
  });
  modalContent.querySelector(".apply-import-all")?.addEventListener("click", () => {
    modalContent.querySelector('[name="applyRemaining"]').value = "yes";
  });
  return closed;
}

async function addHostFileWithPlan(index, file, plan) {
  const pane = panes[index];
  const form = new FormData();
  form.append("file", file);
  form.append("destination", pane.path);
  form.append("targetName", plan.targetName);
  if (pane.partition !== null) form.append("partition", pane.partition);
  if (pane.side !== null) form.append("side", pane.side);
  for (const key of ["attributes", "datestamp", "filetype"]) if (plan[key]) form.append(key, plan[key]);
  const data = await paneOperation(index, "Adding file to image…", () =>
    api(`/api/images/${pane.image.id}/files`, { method: "POST", body: form }));
  pane.image = data.image;
  await loadDirectory(index);
  toast(`${file.name} added`);
}

async function promptImageExtraction(index, file, batch = null) {
  const pane = panes[index];
  const upload = new FormData();
  upload.append("image", file);
  upload.append("targetHardware", "auto");
  setLoading(index, true, `Uploading ${file.name} for preview…`);
  let prepared;
  try {
    const opened = await uploadApi("/api/images", upload, {
      onProgress: (loaded, total) => setLoading(
        index,
        true,
        `Uploading ${file.name} for preview${total ? ` · ${Math.round(loaded * 100 / total)}%` : ""}`
      ),
      onProcessing: () => setLoading(index, true, `Reading ${file.name} contents…`),
    });
    prepared = opened.image;
    const preview = await api(`/api/images/${prepared.id}/preview`);
    const rule = targetNameRule(pane, formats.stem(file.name));
    let sourceConsumed = false;
    if (batch?.acceptAll) {
      const stored = batch.imagePlan || { storageMethod: "extract", targetPath: pane.path, createDirectory: false };
      if (stored.storageMethod === "raw") {
        await api(`/api/images/${prepared.id}`, { method: "DELETE" });
        sourceConsumed = true;
        return addHostFileWithPlan(index, file, { targetName: targetNameRule(pane, file.name).suggested });
      }
      const plan = {
        targetPath: stored.targetPath || pane.path,
        createDirectory: Boolean(stored.createDirectory),
        directoryName: stored.createDirectory ? rule.suggested : null,
      };
      const result = await extractPreparedHostImage(index, prepared, file.name, plan, batch);
      await api(`/api/images/${prepared.id}`, { method: "DELETE" });
      sourceConsumed = true;
      return result;
    }
    const closed = showImageExtractionPlan(index, {
      heading: `Import ${file.name}`,
      sourceName: file.name,
      preview,
      suggestedName: rule.suggested,
      allowRaw: true,
      allowInstall: paneAcceptsInstall(pane),
      batch,
      submitLabel: "Continue",
      onRaw: async choice => {
        if (batch && choice?.applyAll) {
          batch.acceptAll = true;
          batch.imagePlan = { storageMethod: "raw" };
        }
        await api(`/api/images/${prepared.id}`, { method: "DELETE" });
        sourceConsumed = true;
        if (choice?.applyAll) {
          return addHostFileWithPlan(index, file, { targetName: targetNameRule(pane, file.name).suggested });
        }
        setTimeout(() => importHostFile(index, file, true, batch), 0);
      },
      onInstall: async plan => {
        const result = await performInstall(index, prepared.id, file.name, plan);
        await api(`/api/images/${prepared.id}`, { method: "DELETE" });
        sourceConsumed = true;
        return result;
      },
      onExtract: async plan => {
        if (batch && plan.applyAll) {
          batch.acceptAll = true;
          batch.imagePlan = { ...plan, storageMethod: "extract", directoryName: null, applyAll: undefined };
        }
        const result = await extractPreparedHostImage(index, prepared, file.name, plan, batch);
        await api(`/api/images/${prepared.id}`, { method: "DELETE" })
          .then(() => { sourceConsumed = true; })
          .catch(() => {});
        return result;
      },
    });
    closed.then(() => {
      if (!sourceConsumed) api(`/api/images/${prepared.id}`, { method: "DELETE" }).catch(() => {});
    });
    return closed;
  } catch (error) {
    if (prepared) await api(`/api/images/${prepared.id}`, { method: "DELETE" }).catch(() => {});
    toast(`Could not preview ${file.name}: ${error.message}`, true);
  } finally {
    pane.loading = false;
    pane.loadingMessage = "";
    renderPane(index);
  }
}

function extractionPreviewMarkup(preview) {
  const rows = preview.entries || [];
  return `
    <div class="image-import-preview">
      <div class="image-import-preview-head"><strong>Image contents</strong><span>${esc(preview.summary || `${rows.length} item(s)`)}</span></div>
      <div class="image-import-preview-list">
        ${rows.length ? rows.map(item => `
          <div class="image-import-preview-row">
            <span class="preview-kind">${item.type === "dir" ? "▣" : item.type === "disk" ? "▤" : "□"}</span>
            <span><b>${esc(item.name)}</b><small>${esc(item.path || "\\")}${item.detail ? ` · ${esc(item.detail)}` : ""}</small></span>
            <em>${item.size == null ? "" : humanSize(item.size)}</em>
          </div>`).join("") : '<p class="muted">No files were found in this image.</p>'}
      </div>
      ${preview.truncated ? '<small class="preview-truncated">Preview limited to the first 500 objects.</small>' : ""}
    </div>`;
}

function showImageExtractionPlan(index, options) {
  const pane = panes[index];
  const batchLabel = options.batch?.total > 1
    ? `<p class="batch-position">Selected file ${options.batch.current} of ${options.batch.total}</p>`
    : "";
  const canApplyAll = options.batch?.total > options.batch?.current;
  const closed = showModal(`
    <h2>${esc(options.heading)}</h2>
    ${batchLabel}
    <p>Review the source, then choose where its contents should go. Extraction defaults to the folder currently shown in the pane.</p>
    ${extractionPreviewMarkup(options.preview)}
    ${options.allowRaw || options.allowInstall ? `<div class="field"><label>Import as</label><select name="storageMethod">
      <option value="extract">Copy the disk contents in as they are</option>
      ${options.allowInstall ? '<option value="install">Install it onto this drive</option>' : ""}
      ${options.allowRaw ? '<option value="raw">Store the original image as an ordinary file</option>' : ""}
    </select></div>` : '<input type="hidden" name="storageMethod" value="extract">'}
    ${options.allowInstall ? installPlanMarkup(options) : ""}
    <div data-extraction-options>
      <div class="selected-destination"><small>DESTINATION</small><code data-selected-destination>${esc(pane.path)}</code></div>
      <label class="check-field"><input type="checkbox" name="pickDestination" value="yes"> Choose a different existing folder</label>
      <input type="hidden" name="targetPath" value="${esc(pane.path)}">
      <div class="volume-directory-picker" data-directory-picker hidden>
        <div class="directory-picker-head"><button type="button" class="button ghost picker-up">Up</button><code data-picker-path>${esc(pane.path)}</code></div>
        <div class="directory-picker-list" data-picker-list></div>
      </div>
      <label class="check-field"><input type="checkbox" name="createDirectory" value="yes"> Create a new child folder before extracting</label>
      <div class="field" data-extracted-directory hidden><label>New folder name · max 12 characters</label>
        <input name="directoryName" maxlength="12" value="${esc(options.suggestedName)}" disabled></div>
      <div class="help-note">Existing names are never overwritten. A failed or aborted direct extraction restores the working image.</div>
    </div>
    <input type="hidden" name="applyRemaining" value="no">
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button>${canApplyAll ? '<button class="button ghost apply-import-all" value="continue">Continue and apply to all remaining</button>' : ""}<button class="button primary" value="continue">${esc(options.submitLabel)}</button></div>`,
  async form => {
    const applyAll = form.get("applyRemaining") === "yes";
    if (form.get("storageMethod") === "raw") return options.onRaw?.({ applyAll });
    if (form.get("storageMethod") === "install") {
      return options.onInstall({
        mode: form.get("installMode") || "stage",
        title: (form.get("installTitle") || options.suggestedName || "").trim(),
        diskLabel: (form.get("diskLabel") || "").trim(),
        parent: (form.get("installParent") || "").trim(),
        installNow: form.get("installNow") === "yes",
        applyAll,
      });
    }
    return options.onExtract({
      targetPath: form.get("pickDestination") === "yes" ? form.get("targetPath") : pane.path,
      createDirectory: form.get("createDirectory") === "yes",
      directoryName: form.get("directoryName"),
      applyAll,
    });
  });
  bindImageExtractionPlan(index, Boolean(options.allowRaw), options);
  modalContent.querySelector(".apply-import-all")?.addEventListener("click", () => {
    modalContent.querySelector('[name="applyRemaining"]').value = "yes";
  });
  return closed;
}

function bindImageExtractionPlan(index, allowRaw, options = {}) {
  const pane = panes[index];
  const storageMethod = modalContent.querySelector('select[name="storageMethod"]');
  const extractionOptions = modalContent.querySelector("[data-extraction-options]");
  const pickDestination = modalContent.querySelector('input[name="pickDestination"]');
  const targetPath = modalContent.querySelector('input[name="targetPath"]');
  const selectedDestination = modalContent.querySelector("[data-selected-destination]");
  const picker = modalContent.querySelector("[data-directory-picker]");
  const pickerPath = modalContent.querySelector("[data-picker-path]");
  const pickerList = modalContent.querySelector("[data-picker-list]");
  const createDirectory = modalContent.querySelector('input[name="createDirectory"]');
  const directoryField = modalContent.querySelector("[data-extracted-directory]");
  const directoryName = modalContent.querySelector('input[name="directoryName"]');

  const showDirectory = () => {
    directoryField.hidden = !createDirectory.checked;
    directoryName.disabled = !createDirectory.checked;
    directoryName.required = createDirectory.checked;
  };
  const parentOf = path => parentPath(path);
  const loadPicker = async path => {
    pickerList.innerHTML = '<span class="muted">Reading folders…</span>';
    try {
      const data = await api(`/api/images/${pane.image.id}/tree?path=${encodeURIComponent(path)}`);
      if (!modal.open) return;
      targetPath.value = path;
      selectedDestination.textContent = path;
      pickerPath.textContent = path;
      const directories = data.entries.filter(item => item.type === "dir");
      pickerList.innerHTML = directories.length
        ? directories.map(item => `<button type="button" data-directory-name="${esc(item.name)}"><b>▣</b><span>${esc(item.name)}</span></button>`).join("")
        : '<span class="muted">No child folders here.</span>';
      pickerList.querySelectorAll("[data-directory-name]").forEach(button => {
        button.onclick = () => loadPicker(fullPath(path, button.dataset.directoryName));
      });
    } catch (error) {
      pickerList.innerHTML = `<span class="error-text">${esc(error.message)}</span>`;
    }
  };
  pickDestination.onchange = () => {
    picker.hidden = !pickDestination.checked;
    if (pickDestination.checked) loadPicker(targetPath.value || pane.path);
    else {
      targetPath.value = pane.path;
      selectedDestination.textContent = pane.path;
    }
  };
  modalContent.querySelector(".picker-up").onclick = () => loadPicker(parentOf(targetPath.value));
  createDirectory.onchange = showDirectory;
  const installOptions = modalContent.querySelector("[data-install-options]");
  if (storageMethod) {
    storageMethod.onchange = () => {
      extractionOptions.hidden = storageMethod.value !== "extract";
      if (installOptions) installOptions.hidden = storageMethod.value !== "install";
    };
  }
  if (installOptions) bindInstallPlan(index, options);
  showDirectory();
}

//: Whether the `/install/` routes are published by this build. They are, so
//: every control below reaches a service that answers. The flag and the note
//: are kept because a build that ships without the install blueprint has to
//: be able to say so in the dialog rather than failing at the network.
const INSTALL_SERVICE_AVAILABLE = true;
const INSTALL_UNAVAILABLE_NOTE = '<div class="help-warning"><strong>Not available in this build.</strong> The install service is not published here, so these controls are disabled rather than failing at the network.</div>';

//: The three honest ways a floppy becomes something a hard drive runs.
//: Staging leads because it is the only one that cannot half-succeed: it
//: needs no emulator, no network and no per-title knowledge, and what it
//: produces is finishable by hand either here or on the real machine.
const INSTALL_MODES = [
  {
    value: "stage",
    label: "Stage it for installing later",
    detail: "Copies the disk into a staging folder on this drive. Add the rest of a multi-disk set to the same place, then install them together here, or boot the drive and run the title's own installer against the folder.",
  },
  {
    value: "install",
    label: "Install it into a folder on this drive",
    detail: "For a title that runs from wherever it is put. The staged files are moved into the folder you name, keeping the tree the disk had.",
  },
  {
    value: "installer",
    label: "Run the disk's own installer",
    detail: "Boots this drive in Hatari with the disk in A:. Use it for productivity software, which asks questions no tool can answer for you.",
  },
];

function installPlanMarkup(options) {
  return `
    <div data-install-options hidden>
      ${INSTALL_SERVICE_AVAILABLE ? "" : INSTALL_UNAVAILABLE_NOTE}
      <div class="field"><label>Title</label>
        <input name="installTitle" maxlength="60" value="${esc(options.suggestedName || "")}" ${INSTALL_SERVICE_AVAILABLE ? "" : "disabled"}>
        <small>Disks staged under the same title are merged into one tree on this drive.</small></div>
      <div class="field"><label>Disk</label>
        <input name="diskLabel" maxlength="30" placeholder="Disk 1" ${INSTALL_SERVICE_AVAILABLE ? "" : "disabled"}></div>
      <div class="field"><label>Method</label>
        <div class="install-modes">
          ${INSTALL_MODES.map((mode, position) => `
            <label class="check-field install-mode">
              <input type="radio" name="installMode" value="${mode.value}"${position === 0 ? " checked" : ""} ${INSTALL_SERVICE_AVAILABLE ? "" : "disabled"}>
              <span><b>${esc(mode.label)}</b><small>${esc(mode.detail)}</small></span>
            </label>`).join("")}
        </div></div>
      <div data-install-folder hidden>
        <div class="field"><label>Install into</label>
          <input name="installParent" maxlength="60" value="GAMES" ${INSTALL_SERVICE_AVAILABLE ? "" : "disabled"}>
          <small>A folder at the root of this volume, named the way GEMDOS stores it.</small></div>
      </div>
      <label class="check-field" data-install-now hidden>
        <input type="checkbox" name="installNow" value="yes" checked ${INSTALL_SERVICE_AVAILABLE ? "" : "disabled"}> Write it into the drive now, rather than only staging it
      </label>
    </div>`;
}

function bindInstallPlan(index, options) {
  const folderPanel = modalContent.querySelector("[data-install-folder]");
  const installNow = modalContent.querySelector("[data-install-now]");
  const modes = [...modalContent.querySelectorAll('input[name="installMode"]')];
  const chosen = () => modes.find(input => input.checked)?.value || "stage";

  const refresh = () => {
    const mode = chosen();
    folderPanel.hidden = mode !== "install";
    // Staging writes into the drive's staging folder rather than into the
    // title's final home, so "write it in now" is the step that moves it
    // there. Running the installer does not install anything itself.
    installNow.hidden = mode === "installer";
  };
  modes.forEach(input => input.addEventListener("change", refresh));
  refresh();
}

//: Where staged disks live on the drive, unless the operator names another.
//: Staging writes onto the target image so the install can be finished in an
//: emulator or on the real machine, which means this is a GEMDOS path, not a
//: directory on the computer running the application. It has to match
//: DEFAULT_STAGING_PARENT in app/install_service.py, and every component is
//: an 8.3 name because that is all a GEMDOS directory entry can hold.
const DEFAULT_STAGING_PARENT = "INSTALL\\STAGE";

async function showStagedInstallations(index) {
  const pane = panes[index];
  if (!paneAcceptsInstall(pane)) {
    return alertNotice(
      "Staged disks",
      "Staged disks live in a folder on the drive they are destined for, so this needs a volume open.",
      { confirmLabel: "Close" },
    );
  }
  const partition = pane.partition == null ? "" : `&partition=${pane.partition}`;
  const data = await paneOperation(index, "Reading staged titles…", () =>
    api(`/api/images/${pane.image.id}/install/staged?parent=${encodeURIComponent(DEFAULT_STAGING_PARENT)}${partition}`));
  const titles = data.titles || [];
  const rows = titles.map(title => `
    <div class="staged-title" data-name="${esc(title.name)}">
      <div>
        <b>${esc(title.title)}</b>
        <small>${title.diskCount ? `${title.diskCount} disk${title.diskCount === 1 ? "" : "s"} · ` : ""}${title.fileCount} file${title.fileCount === 1 ? "" : "s"} · ${humanSize(title.bytes)}</small>
        <small><code>${esc(title.path)}</code></small>
        ${title.disks.length ? `<small>${esc(title.disks.map(disk => `${disk.label}: ${disk.volume}`).join(" · "))}</small>` : ""}
        ${title.conflicts.length ? `<small class="staged-conflict">${title.conflicts.length} file${title.conflicts.length === 1 ? "" : "s"} differed between disks; the first was kept and the rest are under ${esc(DEFAULT_STAGING_PARENT)}\\CLASH</small>` : ""}
      </div>
      <div class="staged-actions">
        <button type="button" class="button primary staged-install">Install here</button>
        <button type="button" class="button ghost staged-discard">Discard</button>
      </div>
    </div>`).join("");

  showModal(`
    <h2>Staged disks</h2>
    <p>Disks waiting on this drive. Stage every disk of a set under one title, then install it here, or boot the drive in Hatari or a real Atari and run the title's own installer against the staging folder.</p>
    <div class="selected-destination"><small>STAGING FOLDER</small><code>${esc(drivePath(pane.partitionName || pane.image.driveLetter || "", data.root || DEFAULT_STAGING_PARENT))}</code></div>
    <div class="field"><label>Install into</label><input name="stagedParent" maxlength="60" value="GAMES" placeholder="Leave empty for the volume root">
      <small>The folder on this volume that finished titles are moved into.</small></div>
    <div class="staged-title-list">${rows || `<p class="muted">Nothing is staged on this drive. Choose <strong>Install it onto this drive</strong> when you add a disk, and pick <strong>Stage it for installing later</strong>.</p>`}</div>
    <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div>`,
  () => true);

  modalContent.querySelectorAll(".staged-title").forEach(row => {
    const name = row.dataset.name;
    row.querySelector(".staged-install")?.addEventListener("click", async () => {
      const parent = modalContent.querySelector('input[name="stagedParent"]')?.value.trim() || "";
      modal.close();
      try {
        const result = await trackedPaneOperation(index, "Installing a staged title…", operationId =>
          api(`/api/images/${pane.image.id}/install/staged`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name, parent, stagingParent: DEFAULT_STAGING_PARENT,
              partition: pane.partition, operationId,
            }),
          }));
        pane.image = result.image;
        await loadDirectory(index);
        toast(`${result.title} installed into ${result.path}`);
      } catch (error) {
        toast(error.message, true);
      }
    });
    row.querySelector(".staged-discard")?.addEventListener("click", async () => {
      // Discarding deletes the extracted disks off the drive, so it is
      // confirmed rather than acted on from a single click. The original
      // images are untouched, which is worth saying: it is the difference
      // between an inconvenience and a loss.
      const title = row.querySelector("b").textContent;
      if (!await confirmChoice(
        "Discard these staged disks?",
        `The staging folder for “${title}” is deleted from ${volumeLabel(pane)}${DEFAULT_STAGING_PARENT}.`,
        { confirmLabel: "Discard", danger: true, note: "The original disk images are untouched, so the set can be staged again." },
      )) return;
      modal.close();
      try {
        await api(`/api/images/${pane.image.id}/install/staged/discard`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, stagingParent: DEFAULT_STAGING_PARENT, partition: pane.partition }),
        });
        await loadDirectory(index);
        toast("Staged title discarded");
      } catch (error) {
        toast(error.message, true);
      }
      showStagedInstallations(index);
    });
  });
}

//: How a volume is named in a sentence, and what a path on it is written
//: after: the GEMDOS drive letter with its colon when the pane knows one,
//: because that is what an operator sees on the machine, and the image file
//: name with a separating space when it does not.
function volumeLabel(pane) {
  if (pane?.partitionName) return `${String(pane.partitionName).replace(/:$/, "")}:`;
  return pane?.image?.name ? `${pane.image.name} ` : "";
}


//: The hard-disk drivers a TOS machine can boot from, and the one case where
//: it needs none at all. The list the service publishes is the authority, and
//: it also says which of them the operator has actually supplied a copy of;
//: this is the fallback wording used before that answer arrives.
const DRIVE_DRIVERS = [
  { value: "driver-emutos-builtin", label: "None · boot driverless under EmuTOS", detail: "EmuTOS reads ACSI, SCSI and IDE drives itself. Nothing is written to the root sector, so the drive stays readable by any machine running EmuTOS." },
  { value: "driver-ahdi", label: "Atari AHDI", detail: "Atari's own driver, written to the root sector with AHDI.PRG in the AUTO folder. It is limited to 16 MB partitions on TOS 1.x." },
  { value: "driver-hddriver", label: "HDDRIVER", detail: "Uwe Seimet's driver, the usual choice for large partitions and modern interfaces such as ACSI2STM and UltraSatan." },
  { value: "driver-pp", label: "PP driver", detail: "Peter Putnik's free driver for ACSI, SCSI and IDE drives." },
  { value: "driver-icd", label: "ICD Pro driver", detail: "Supplied with ICD host adapters, and it also drives most other ACSI hardware." },
];

//: How a drive describes its own preparation in one line. Everything in it is
//: read off the drive rather than remembered here, so a drive prepared on
//: another machine reads as accurately as one prepared in this application.
function drivePreparationSummary(state) {
  if (!state) return "";
  const parts = [
    state.scheme === "mbr" ? "PC partition table" : `${String(state.scheme || "").toUpperCase()} partition table`,
    state.byteSwapped ? "stored byte-swapped" : "",
    state.rootSectorExecutable ? "root sector executable" : "root sector inert",
    state.driver?.installed ? `${state.driver.file}${state.driver.version ? ` ${state.driver.version}` : ""} in the partition root` : "no driver file",
    state.desktop?.length ? state.desktop.join(" and ") : "no desktop configuration",
  ];
  return parts.filter(Boolean).join(" · ");
}

//: Preparing a drive so a machine can start from it: writing a hard-disk
//: driver onto the root sector, or declaring that EmuTOS will read the drive
//: itself and no driver is needed.
async function showPrepareDrive(index) {
  const pane = panes[index];
  if (!paneAcceptsInstall(pane)) {
    return alertNotice(
      "Prepare this drive",
      "A driver is written to the drive it is going to boot, so open a partition on a hard drive first.",
      { confirmLabel: "Close" },
    );
  }
  const target = volumeLabel(pane) || pane.image.name;
  const partition = pane.partition == null ? "" : `?partition=${pane.partition}`;
  let state = null;
  let desktops = { desktops: [], available: [], recommended: null };
  try {
    const profile = activeWorkbenchProfile();
    const machine = profile.profile?.machine || profile.machine || "st";
    const memory = Number(profile.memoryBytes || profile.profile?.memoryBytes || 0);
    const query = new URLSearchParams({ machine, memory: String(memory) });
    [state, desktops] = await paneOperation(index, "Reading how this drive is prepared…", async () => {
      const [preparation, catalogue] = await Promise.all([
        api(`/api/images/${pane.image.id}/install/driver${partition}`),
        api(`/api/install/desktops?${query}`).catch(() => ({ desktops: [], available: [], recommended: null })),
      ]);
      return [preparation.preparation, catalogue];
    });
  } catch (error) {
    return toast(error.message, true);
  }
  const published = state.drivers?.length ? state.drivers : DRIVE_DRIVERS.map(driver => ({ id: driver.value, label: driver.label, note: driver.detail }));
  const supplied = Object.fromEntries((state.available || []).map(row => [row.id, row]));
  const detailFor = id => {
    const driver = published.find(item => item.id === id);
    const copy = supplied[id];
    const note = driver?.note || DRIVE_DRIVERS.find(item => item.value === id)?.detail || "";
    if (!copy || copy.available) return note;
    // A driver that may be fetched is offered without a copy, because
    // choosing it is what fetches it. One that is sold says so instead.
    if (copy.obtainable !== false) {
      return `${note} No copy here yet, so choosing this downloads one.`;
    }
    return `${note} ${driver?.licence || "No copy of this driver was found, so it cannot be installed yet."}`;
  };
  const closed = showModal(`
    <h2>Prepare this drive</h2>
    <p>Makes ${esc(target)} startable, either by installing a hard-disk driver on it or by declaring that EmuTOS will read the drive without one.</p>
    <div class="selected-destination"><small>THIS DRIVE NOW</small><code>${esc(drivePreparationSummary(state))}</code></div>
    <div class="help-note"><strong>Your own driver:</strong> Atari File Forge does not ship AHDI, HDDRIVER, the PP driver or the ICD driver and cannot fetch them. Put the files you own in <code>~/.config/atari-file-forge/drivers</code> or <code>firmware/drivers</code>, unpacked as they were published. EmuTOS needs no driver at all.</div>
    <div class="field"><label>Hard-disk driver</label>
      <select name="driveDriver">
        ${published.map(driver => {
          const copy = supplied[driver.id];
          const obtainable = copy ? copy.obtainable !== false : true;
          const state = copy && !copy.available
            ? (driver.free ? " · downloads when chosen" : " · not supplied")
            : (copy?.version ? ` · ${copy.version}` : "");
          return `<option value="${esc(driver.id)}"${obtainable ? "" : " disabled"}>${esc(driver.label)}${esc(state)}</option>`;
        }).join("")}
      </select>
      <small data-driver-detail>${esc(detailFor(published[0]?.id))}</small></div>
    ${desktopReplacementField(desktops)}
    <label class="check-field"><input type="checkbox" name="createFolders" value="yes" checked> Create the folders a prepared drive expects (AUTO, GEMSYS, GAMES)</label>
    <label class="check-field"><input type="checkbox" name="writeDesktop" value="yes" checked> Write a desktop configuration if this volume has none</label>
    <div class="help-note">Files already on the volume are left alone, so an existing drive is added to rather than replaced, and preparing twice does not undo work done in between.</div>
    <div class="modal-actions">
      <button class="button ghost" value="cancel">Close</button>
      <button class="button primary" value="prepare" data-prepare-drive>Prepare the drive</button>
    </div>`,
  async form => {
    const result = await trackedPaneOperation(index, "Preparing the drive…", operationId =>
      api(`/api/images/${pane.image.id}/install/driver`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          driver: form.get("driveDriver"),
          partition: pane.partition,
          folder: desktopFolder,
          createFolders: form.get("createFolders") === "yes",
          desktop: form.get("writeDesktop") === "yes",
          operationId,
        }),
      }));
    pane.image = result.image;
    // The multitasker goes in first, because AUTO runs its programs in the
    // order the folder holds them and Geneva has to be up before NeoDesk
    // loads under it. Installing in this order is what puts them in that
    // order on the drive.
    const catalogued = Object.fromEntries((desktops.desktops || []).map(row => [row.id, row]));
    const chosen = form.getAll("driveDesktop")
      .map(String)
      .sort((left, right) => Number(catalogued[right]?.companion) - Number(catalogued[left]?.companion));
    const warnings = [];
    for (const desktop of chosen) {
      const installed = await trackedPaneOperation(
        index,
        `Installing ${catalogued[desktop]?.label || "the desktop"}…`,
        operationId => api(`/api/images/${pane.image.id}/install/desktop-replacement`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            desktop,
            partition: pane.partition,
            folder: desktopFolder,
            operationId,
          }),
        }),
      );
      pane.image = installed.image;
      warnings.push(...(installed.desktop.warnings || []));
      const kept = installed.desktop.kept || [];
      if (kept.length) {
        toast(`${installed.desktop.label}: ${kept.join(", ")} already on the drive, left alone.`);
      }
      toast(`${installed.desktop.label} installed into ${installed.desktop.folder} on ${target}.`);
    }
    // The same caution comes back from each of them, so say it once.
    [...new Set(warnings)].forEach(warning => toast(warning, true));
    await loadDirectory(index);
    (result.warnings || []).forEach(warning => toast(warning, true));
    toast(result.driver.installed
      ? `${result.label} installed on ${target}.`
      : `${target} prepared to start driverless under EmuTOS.`);
  });
  //: The note under the picker is the whole of what tells an operator what
  //: they are choosing, so it follows the choice rather than describing only
  //: the first entry.
  const picker = modalContent.querySelector('[name="driveDriver"]');
  const detail = modalContent.querySelector("[data-driver-detail]");
  picker?.addEventListener("change", () => { detail.textContent = detailFor(picker.value); });
  const folderButton = modalContent.querySelector("[data-choose-desktop-folder]");
  const folderNote = modalContent.querySelector("[data-desktop-folder]");
  folderButton?.addEventListener("click", async () => {
    const folder = await chooseSourceFolder();
    if (!folder) return;
    desktopFolder = folder;
    folderNote.textContent = `Looking in ${folder}`;
    // What is installable changes with the folder, so ask again and rebuild
    // the list rather than leaving one that describes somewhere else. What
    // was ticked is put back wherever it is still available.
    try {
      const refreshed = await api(`/api/install/desktops?${new URLSearchParams({ folder })}`);
      desktops = { ...desktops, available: refreshed.available };
      const ticked = new Set(
        [...modalContent.querySelectorAll('[name="driveDesktop"]:checked')].map(box => box.value),
      );
      const list = modalContent.querySelector(".install-modes");
      list.innerHTML = desktopReplacementOptions(desktops);
      list.querySelectorAll('[name="driveDesktop"]').forEach(box => {
        box.checked = ticked.has(box.value) && !box.disabled;
      });
    } catch (error) { toast(error.message, true); }
  });
  return closed;
}

//: The native host answers with a real path, because it is the server that
//: reads the folder. A browser cannot give one at all, so the button that
//: asks for it is only offered where it can be answered.
function canChooseSourceFolder() {
  return Boolean(window.webkit?.messageHandlers?.atariDesktop);
}

function chooseSourceFolder() {
  if (!canChooseSourceFolder()) return Promise.resolve("");
  return new Promise(resolve => {
    pendingSourceFolder = resolve;
    window.webkit.messageHandlers.atariDesktop.postMessage("choose-source-folder");
  });
}

let pendingSourceFolder = null;
let desktopFolder = "";

//: The replacement desktop. The built-in TOS desktop has no icons of your
//: own, no program groups and no way to find a file, so every serious machine
//: acquired a replacement. What this offers is the free ones, downloaded when
//: they are wanted, your own copy of the rest, and the recommendation for the
//: machine the drive is being built for.
//:
//: More than one of these can be wanted at once: Geneva is not a desktop but
//: a multitasker that runs under one, and NeoDesk was written to sit on it.
//: So the choice is a list to tick rather than one to pick, and ticking
//: nothing leaves the built-in TOS desktop alone.
function desktopReplacementField(catalogue) {
  if (!(catalogue.desktops || []).length) return "";
  return `<div class="field"><label>Replacement desktop</label>
      <div class="install-modes">${desktopReplacementOptions(catalogue)}</div>
      <small>Tick nothing to keep the built-in TOS desktop.</small>
      ${canChooseSourceFolder() ? `<div class="desktop-source-choice">
        <button type="button" class="button compact" data-choose-desktop-folder>Other…</button>
        <small data-desktop-folder>Looks in the usual places, and downloads a free desktop if it is not there.</small>
      </div>` : ""}</div>`;
}

function desktopReplacementOptions(catalogue) {
  const desktops = catalogue.desktops || [];
  const supplied = Object.fromEntries((catalogue.available || []).map(row => [row.id, row]));
  const preferred = catalogue.recommended?.id;
  return desktops.map(desktop => {
    const copy = supplied[desktop.id];
    // A free desktop with somewhere to download it from is offered whether or
    // not a copy is here, because ticking it is what fetches it. Only one that
    // is somebody's property and has not been supplied is refused.
    const obtainable = copy ? copy.obtainable !== false : true;
    const here = Boolean(copy?.available);
    const state = here
      ? (copy.version ? `Version ${copy.version} is ready to install.` : "A copy is ready to install.")
      : desktop.free
        ? "No copy here yet, so ticking this downloads one."
        : `No copy here yet. ${desktop.licence}`;
    // One sentence in a list somebody is scanning. The whole of it is in the
    // firmware notes for anyone who wants the rest.
    const summary = String(desktop.note || "").split(". ")[0];
    const recommended = preferred === desktop.id && obtainable
      ? `<b class="desktop-recommended">Recommended.</b> `
      : "";
    const kind = desktop.companion ? " · runs under a desktop" : "";
    return `<label class="check-field install-mode">
      <input type="checkbox" name="driveDesktop" value="${esc(desktop.id)}"${obtainable ? "" : " disabled"}${preferred === desktop.id && obtainable ? " checked" : ""}>
      <span><b>${esc(desktop.label)}${esc(kind)}</b><small>${recommended}${esc(summary)}. ${esc(state)}</small></span>
    </label>`;
  }).join("");
}

//: Running a title's own installer. There is no tree to copy: the installer
//: is Atari code that asks where things should go, reads what the live system
//: has loaded and writes the result itself. So this puts the machine in the
//: state the installer needs and hands over the keyboard.
async function showTitleInstaller(index) {
  const pane = panes[index];
  if (!paneAcceptsInstall(pane)) {
    return alertNotice(
      "Run a title's own installer",
      "An installer writes onto the drive it is installing to, so open a partition on one first.",
      { confirmLabel: "Close" },
    );
  }
  //: The installer reads its disks out of the floppy drives, so the disks
  //: have to be images that are already open. An Atari has two drives, which
  //: is why exactly two are offered and the rest are swapped by hand.
  const floppies = panes
    .map((item, position) => ({ item, position }))
    .filter(({ item, position }) => item.image && position !== index && item.image.kind !== "hd");
  if (!floppies.length) {
    return alertNotice(
      "Run a title's own installer",
      "Open the title's first disk in another pane first: the installer reads it out of drive A:, so it has to be an image this session already has.",
      { confirmLabel: "Close" },
    );
  }
  const options = floppies.map(({ item, position }) =>
    `<option value="${esc(item.image.id)}">${esc(paneLabel(position))}</option>`).join("");
  return showModal(`
    <h2>Run a title's own installer</h2>
    <p>Boots ${esc(volumeLabel(pane) || pane.image.name)} in Hatari with the title's first disk in drive A:, so its own installer can ask its questions and write its own files.</p>
    <div class="help-note"><strong>The installer belongs to the title.</strong> Productivity software installs itself by running a program that reads the machine it finds and asks where things should go. It cannot be run unattended, so this puts everything in place and then hands you the machine.</div>
    <div class="field"><label>Drive A:</label>
      <select name="diskA">${options}</select>
      <small>An ST, MSA, DIM, STX or HFE image of the disk you own, already open in another pane. Nothing is downloaded.</small></div>
    <div class="field"><label>Drive B:</label>
      <select name="diskB"><option value="">Leave empty</option>${options}</select>
      <small>An Atari has two floppy drives. Swap the rest of the set as the installer asks for them.</small></div>
    <div class="modal-actions">
      <button class="button ghost" value="cancel">Close</button>
      <button class="button primary" value="boot" data-boot-installer>Boot with the disk</button>
    </div>`,
  async form => {
    const disks = [form.get("diskA"), form.get("diskB")].filter(Boolean);
    const result = await paneOperation(index, "Starting Hatari…", () =>
      api(`/api/images/${pane.image.id}/install/emulator`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ disks, partition: pane.partition }),
      }));
    toast(result.result.summary);
  });
}

//: Whether this pane is showing a GEMDOS volume that a disk's contents can be
//: extracted into, rather than a container that merely holds one.
//:
//: A hard drive answers for the partition currently open, not for the drive as
//: a whole. Asking about the image's own kind said "hd" whichever volume was
//: open, so inserting a disk image into a partitioned drive -- the case the
//: install modes exist for -- never offered to extract or install it, and
//: quietly stored the image as an ordinary file instead.
function paneHoldsVolume(pane) {
  if (!pane?.image || pane.archivePath || pane.image.readOnly) return false;
  if (pane.image.kind === "hd") return pane.partition !== null;
  return pane.image.kind === "gemdos";
}

//: A pane can receive an install only when it is a volume on a hard drive.
//: A floppy has nowhere to install to, and a partition table is not a volume.
function paneAcceptsInstall(pane) {
  if (!pane?.image || pane.image.readOnly) return false;
  if (pane.image.kind === "hd") return pane.partition !== null;
  return Boolean(pane.image.hardDisk) && pane.image.kind === "gemdos";
}

async function performInstall(index, sourceImageId, sourceName, plan) {
  if (!INSTALL_SERVICE_AVAILABLE) {
    toast("Installing a title onto a drive is not yet available in this build.", true);
    return null;
  }
  const pane = panes[index];
  const title = plan.title || formats.stem(sourceName);

  // Every mode stages first. It is the one step that always works, and it
  // means an install that fails later has still preserved the disk's contents
  // somewhere the operator can finish by hand.
  const staged = await trackedPaneOperation(index, `Staging ${sourceName}…`, operationId =>
    api(`/api/images/${pane.image.id}/install/stage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sourceImage: sourceImageId,
        sourcePartition: null,
        partition: pane.partition,
        stagingParent: DEFAULT_STAGING_PARENT,
        title,
        diskLabel: plan.diskLabel || null,
        operationId,
      }),
    })).then(data => {
      pane.image = data.image;
      return data.staged;
    });

  if (plan.mode === "installer") {
    const result = await paneOperation(index, "Starting Hatari…", () =>
      api(`/api/images/${pane.image.id}/install/emulator`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ disks: [sourceImageId], partition: pane.partition }),
      }));
    toast(result.result.summary);
    return staged;
  }

  if (!plan.installNow) {
    await loadDirectory(index);
    toast(`${title} staged into ${staged.path} as ${staged.diskCount} disk(s). Install it when the set is complete.`);
    return staged;
  }

  const result = await trackedPaneOperation(index, `Installing ${title}…`, operationId =>
    api(`/api/images/${pane.image.id}/install/staged`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: staged.name,
        parent: plan.mode === "install" ? (plan.parent || "GAMES") : "",
        stagingParent: DEFAULT_STAGING_PARENT,
        partition: pane.partition,
        operationId,
      }),
    }));
  pane.image = result.image;
  await loadDirectory(index);
  toast(`${title} installed into ${result.path}.`);
  return staged;
}

async function extractPreparedHostImage(index, sourceImage, sourceName, plan, batch = null) {
  const pane = panes[index];
  const destinationLabel = plan.createDirectory ? plan.directoryName : plan.targetPath;
  const data = await trackedPaneOperation(index, `Extracting ${sourceName} into ${destinationLabel}…`, operationId =>
    api("/api/transfer-image-to-directory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sourceImage: sourceImage.id,
        targetImage: pane.image.id,
        targetPath: plan.targetPath,
        directoryName: plan.directoryName,
        createDirectory: plan.createDirectory,
        operationId,
      }),
    }));
  pane.image = data.image;
  await loadDirectory(index);
  toast(`${sourceName} contents extracted into ${data.path}`);
}

function selectedLaunchCandidateIndex(metadata) {
  const launchCandidates = metadata.launchCandidates || [];
  let selected = launchCandidates.findIndex(item =>
    item.name.toLowerCase() === String(metadata.filename || "").toLowerCase()
    && item.path === metadata.path);
  if (selected < 0) {
    selected = launchCandidates.findIndex(item =>
      item.name.toLowerCase() === String(metadata.filename || "").toLowerCase());
  }
  return selected < 0 && launchCandidates.length === 1 ? 0 : selected;
}

function launchCandidateOptions(metadata) {
  const launchCandidates = metadata.launchCandidates || [];
  const selected = selectedLaunchCandidateIndex(metadata);
  return `
    <option value="">Choose a file…</option>
    ${launchCandidates.map((item, offset) =>
      `<option value="${offset}" ${offset === selected ? "selected" : ""}>${esc(item.path === metadata.path ? item.name : `${item.path} · ${item.name}`)}</option>`
    ).join("")}`;
}

function hasObviousLaunchCandidate(metadata) {
  return metadata.launchObvious === true && selectedLaunchCandidateIndex(metadata) >= 0;
}

function setWorkspaceClipboard(index, mode) {
  const pane = panes[index];
  const items = clipboardItemsForPane(index);
  if (!items.length) return toast("Select one or more files or folders first.", true);
  clearWorkspaceClipboard("", false);
  workspaceClipboard = {
    mode,
    kind: "files",
    items,
    sourceImage: pane.image.id,
    sourceName: pane.image.name,
    createdAt: Date.now(),
  };
  panes.forEach((_item, paneIndex) => renderPane(paneIndex, true));
  toast(`${items.length} item${items.length === 1 ? "" : "s"} ${mode === "cut" ? "cut" : "copied"}. Choose a destination and paste.`);
}

async function refreshClipboardImages(imageIds) {
  for (let index = 0; index < panes.length; index += 1) {
    if (!imageIds.has(panes[index].image?.id)) continue;
    await refreshCurrentView(index, true);
  }
}

async function deleteCutFileSources(clipboard) {
  const first = clipboard.items[0];
  const data = await api(`/api/images/${first.image}/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      partition: first.partition,
      side: first.side,
      items: clipboard.items.map(item => ({ path: item.path, recursive: item.recursive })),
    }),
  });
  await refreshClipboardImages(new Set([first.image]));
  return data;
}

async function pasteFileItems(index, clipboard) {
  const pane = panes[index];
  const sameImage = clipboard.items.every(item => item.image === pane.image.id);
  const success = await transferFiles(index, clipboard.items);
  if (!success) return false;
  const movedInternally = sameImage && (isGemdosPane(pane) || pane.image.kind === "rom");
  if (clipboard.mode === "cut" && !movedInternally) {
    await deleteCutFileSources(clipboard);
    toast(`${clipboard.items.length} source item${clipboard.items.length === 1 ? "" : "s"} removed after paste.`);
  }
  return true;
}

async function pasteWorkspaceClipboard(index) {
  if (!workspaceClipboard) return;
  const clipboard = workspaceClipboard;
  clipboardMutationInProgress = true;
  try {
    const success = await pasteFileItems(index, clipboard);
    return success;
  } catch (error) {
    toast(error.message, true);
    return false;
  } finally {
    clipboardMutationInProgress = false;
    clearWorkspaceClipboard("", true);
  }
}

async function transferFiles(targetIndex, sources, targetPath = null) {
  const target = panes[targetIndex];
  if (!target.image || (target.image.kind === "hd" && target.partition === null)) return toast("Open a destination volume first.", true);
  if (!Array.isArray(sources) || !sources.length) return;
  const destination = targetPath || target.path;
  const movingWithinRom = target.image.kind === "rom"
    && !(clipboardMutationInProgress && workspaceClipboard?.mode === "copy")
    && sources.every(source => source.image === target.image.id && Number.isInteger(source.romBank ?? Number(String(source.path).replace("bank:", ""))));
  if (movingWithinRom) {
    const targetStart = String(destination).startsWith("bank:")
      ? Number(String(destination).slice(5))
      : Number(target.image.rom?.bankCount || 0);
    const banks = sources.map(source => Number(source.romBank ?? String(source.path).replace("bank:", "")));
    const data = await paneOperation(targetIndex, `Moving ${banks.length} ROM bank${banks.length === 1 ? "" : "s"}…`, () => api(`/api/images/${target.image.id}/rom-banks/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ banks, targetStart }),
    }));
    target.image = data.image;
    await loadDirectory(targetIndex);
    setSelection(target, data.banks.map(String), String(data.banks[0]));
    renderPane(targetIndex, true);
    toast(`${banks.length} ROM bank${banks.length === 1 ? "" : "s"} moved`);
    return true;
  }
  // One /move serves every GEMDOS volume, whether it is a floppy or a
  // partition on a drive, because they are the same filing system.
  const movingWithinVolume = isGemdosPane(target)
    && sources.every(source => source.image === target.image.id);
  if (movingWithinVolume) {
    return performVolumeMoves(targetIndex, sources, destination);
  }
  if (sources.some(source => source.pane === targetIndex) && target.image.kind !== "rom") {
    return toast("Files can only be moved within the same GEMDOS volume.", true);
  }
  const transfers = sources.map((source, index) => ({
    source,
    index,
    rule: targetNameRule(target, source.name)
  }));
  if (transfers.some(item => !item.rule.valid)) {
    return new Promise(resolve => {
      let submitted = false;
      const closed = showModal(`
      <div class="transfer-batch">
        <h2>Check destination names</h2>
        <p>Names must follow the destination filesystem’s rules. Suggested replacements are ready for any incompatible names.</p>
        <div class="transfer-name-list">
          ${transfers.map(item => `<div class="field">
            <label>${esc(item.source.name)} · max ${item.rule.limit} characters</label>
            <input name="targetName${item.index}" maxlength="${item.rule.limit}" value="${esc(item.rule.valid ? item.source.name : item.rule.suggested)}" required>
          </div>`).join("")}
        </div>
        <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="copy">Copy ${transfers.length} item${transfers.length === 1 ? "" : "s"}</button></div>
      </div>`,
      async form => {
        submitted = true;
        const renamed = transfers.map(item => ({
          ...item.source,
          targetName: form.get(`targetName${item.index}`)
        }));
        setTimeout(async () => resolve(await reviewAndPerformTransfers(targetIndex, renamed, destination)), 0);
        return true;
      });
      closed.then(() => { if (!submitted) resolve(false); });
    });
  }
  return reviewAndPerformTransfers(
    targetIndex,
    sources.map(source => ({ ...source, targetName: source.name })),
    destination,
  );
}

function transferCompatibilityChanges(transfers) {
  return transfers.map(transfer => ({
    name: transfer.targetName || transfer.name,
    nameIsLeaf: true,
    source: transfer.path || transfer.name,
    type: transfer.recursive ? "directory" : (transfer.type || "file"),
    attributes: transfer.attributes || transfer.attr || "",
    datestamp: transfer.datestamp || "",
    filetype: transfer.filetype || "",
  }));
}

async function requestCompatibilityReport(index, operation, sourceKind, changes) {
  const pane = panes[index];
  return trackedPaneOperation(index, "Building compatibility report", operationId => api(`/api/images/${pane.image.id}/preflight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ operation, sourceKind, targetKind: pane.image.kind, changes, operationId }),
  }), { abortMode: "read-only" });
}

function compatibilityReportMarkup(report, { heading = "Review compatibility before continuing", continueLabel = "Continue" } = {}) {
  return `<div class="analysis-dialog wide-analysis compatibility-review"><small>CROSS-FORMAT PREFLIGHT / NO IMAGE WRITES</small><h2>${esc(heading)}</h2>
    <p>${esc(report.summary)}. Review every conversion and loss before the destination image is changed.</p>
    <div class="preflight-list">${report.items.map(item => `<article><b>${item.index + 1}</b><span><strong>${esc(item.sourceName)}${item.targetName !== item.sourceName ? ` → ${esc(item.targetName)}` : ""}</strong><small>${esc(item.source)} · ${esc(item.type)}${item.metadata.load ? ` · load ${esc(item.metadata.load)}` : ""}${item.metadata.execute ? ` · execute ${esc(item.metadata.execute)}` : ""}</small>${[...item.conversions, ...item.losses].map(note => `<em>${esc(note)}</em>`).join("")}</span></article>`).join("")}</div>
    <div class="finding-list">${report.issues.map(item => `<p class="finding ${esc(item.severity)}"><b>${esc(item.severity)}</b>${esc(item.message)}</p>`).join("") || '<p class="finding pass"><b>ready</b>No conversion loss or blocking clash was detected.</p>'}</div>
    <div class="modal-actions"><button class="button ghost" type="button" data-export-preflight="json">Export JSON</button><button class="button ghost" type="button" data-export-preflight="markdown">Export Markdown</button><button class="button ghost" value="cancel">Cancel</button><button class="button primary" name="action" value="continue" ${report.canProceed ? "" : "disabled"}>${esc(continueLabel)}</button></div></div>`;
}

function wireCompatibilityExports(report, imageName) {
  modalContent.querySelector('[data-export-preflight="json"]')?.addEventListener("click", () => {
    const documentValue = { ...report }; delete documentValue.markdown;
    downloadJson(documentValue, `${pathNameWithoutExtension(imageName)}-compatibility-report.json`);
  });
  modalContent.querySelector('[data-export-preflight="markdown"]')?.addEventListener("click", () => downloadDocument(
    `${pathNameWithoutExtension(imageName)}-compatibility-report.md`, report.markdown, "text/markdown;charset=utf-8",
  ));
}

function reviewCompatibilityReport(index, report, options = {}) {
  return new Promise(resolve => {
    let accepted = false;
    const closed = showModal(compatibilityReportMarkup(report, options), async form => {
      accepted = form.get("action") === "continue";
      resolve(accepted);
    });
    wireCompatibilityExports(report, panes[index].image.name);
    closed.then(() => { if (!accepted) resolve(false); });
  });
}

async function reviewAndPerformTransfers(targetIndex, transfers, destination) {
  const target = panes[targetIndex];
  const sourceKinds = new Set(transfers.map(transfer => panes[transfer.pane]?.image?.kind || "unknown"));
  const crossFormat = sourceKinds.size !== 1 || !sourceKinds.has(target.image.kind);
  if (crossFormat) {
    try {
      const report = await requestCompatibilityReport(
        targetIndex,
        "cross-format-transfer",
        sourceKinds.size === 1 ? [...sourceKinds][0] : "mixed",
        transferCompatibilityChanges(transfers),
      );
      if (!await reviewCompatibilityReport(targetIndex, report, {
        heading: `Copy to ${target.image.name}`,
        continueLabel: `Copy ${transfers.length} item${transfers.length === 1 ? "" : "s"}`,
      })) return false;
    } catch (error) {
      toast(error.message, true);
      return false;
    }
  }
  return performTransfers(targetIndex, transfers, destination);
}

async function performVolumeMoves(targetIndex, sources, destination) {
  const target = panes[targetIndex];
  const items = sources
    .map(source => ({
      source: source.path,
      destination: fullPath(destination, source.name),
    }))
    .filter(item => item.source.toLowerCase() !== item.destination.toLowerCase());
  if (!items.length) { toast("Those items are already in this folder."); return false; }
  setLoading(
    targetIndex,
    true,
    items.length === 1
      ? `Moving ${sources[0].name}…`
      : `Moving ${items.length} selected items…`,
  );
  try {
    const data = await api(`/api/images/${target.image.id}/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ partition: target.partition, side: target.side, items }),
    });
    await refreshSharedVolumePanes(target.image.id, data.image, data.moved);
    toast(`${items.length} item${items.length === 1 ? "" : "s"} moved`);
    return true;
  } catch (error) {
    target.loading = false;
    renderPane(targetIndex);
    toast(error.message, true);
    return false;
  }
}

async function refreshSharedVolumePanes(imageId, image, moves = [], deleted = null) {
  const directoryMoves = [...moves]
    .filter(move => move.isDirectory)
    .sort((left, right) => right.source.length - left.source.length);
  for (let index = 0; index < panes.length; index += 1) {
    const pane = panes[index];
    if (pane.image?.id !== imageId) continue;
    for (const move of directoryMoves) {
      if (pane.path.toLowerCase() === move.source.toLowerCase()) {
        pane.path = move.destination;
        break;
      }
      if (pane.path.toLowerCase().startsWith(`${move.source}\\`.toLowerCase())) {
        pane.path = move.destination + pane.path.slice(move.source.length);
        break;
      }
    }
    const deletedItems = Array.isArray(deleted) ? deleted : deleted ? [deleted] : [];
    const deletedAncestor = deletedItems.find(item =>
      item.isDirectory
      && (
        pane.path.toLowerCase() === item.path.toLowerCase()
        || pane.path.toLowerCase().startsWith(`${item.path}\\`.toLowerCase())
      )
    );
    if (deletedAncestor) {
      pane.path = parentPath(deletedAncestor.path);
    }
    pane.image = image;
    await loadDirectory(index);
  }
}

async function performTransfers(targetIndex, transfers, destination = null) {
  const target = panes[targetIndex];
  const targetDirectory = destination || target.path;
  setLoading(targetIndex, true, transfers.length === 1 ? "Copying between images…" : `Copying 1 of ${transfers.length}…`);
  try {
    for (const [index, transfer] of transfers.entries()) {
      target.loadingMessage = transfers.length === 1
        ? `Copying ${transfer.name}…`
        : `Copying ${index + 1} of ${transfers.length}: ${transfer.name}…`;
      target.progressCurrent = index;
      target.progressTotal = transfers.length;
      renderPane(targetIndex);
      const romStart = target.image.kind === "rom" && String(targetDirectory).startsWith("bank:")
        ? Number(String(targetDirectory).slice(5))
        : null;
      const targetPath = target.image.kind === "rom"
        ? (romStart == null ? "" : `bank:${romStart + index}`)
        : fullPath(targetDirectory, transfer.targetName);
      const data = await api("/api/transfer", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceImage: transfer.image, sourcePartition: transfer.partition, sourcePath: transfer.path,
          sourceSide: transfer.side,
          targetImage: target.image.id, targetPartition: target.partition, targetSide: target.side,
          targetPath,
          recursive: transfer.recursive
        })
      });
      target.image = data.image;
      target.progressCurrent = index + 1;
    }
    target.progressCurrent = null;
    target.progressTotal = null;
    await loadDirectory(targetIndex);
    toast(transfers.length === 1
      ? `${transfers[0].name} copied as ${transfers[0].targetName}`
      : `${transfers.length} items copied`);
    return true;
  } catch (error) {
    target.loading = false;
    target.progressCurrent = null;
    target.progressTotal = null;
    renderPane(targetIndex);
    toast(error.message, true);
    return false;
  }
}

async function setSelectedAccess(index, writable) {
  const pane = panes[index];
  const entries = selectedEntries(index);
  if (!entries.length) return toast("Select one or more files or folders.", true);
  const paths = entries.map(entry => entryImagePath(pane, entry));
  const accessLabel = writable ? "writable" : "read-only";
  try {
    const data = await paneOperation(index, `Marking ${entries.length} item${entries.length === 1 ? "" : "s"} ${accessLabel}…`, () => api(`/api/images/${pane.image.id}/lock`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ partition: pane.partition, side: pane.side, paths, unlock: writable })
    }));
    pane.image = data.image;
    await loadDirectory(index, true);
    toast(`${entries.length} item${entries.length === 1 ? "" : "s"} marked ${accessLabel}`);
  } catch (error) { toast(error.message, true); }
}

async function validateImage(index) {
  const pane = panes[index];
  if (pane.image.kind === "hd" && pane.partition === null) return toast("Select a partition to check.");
  try {
    const data = await paneOperation(index, "Checking filesystem structure…", () => api(`/api/images/${pane.image.id}/validate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ partition: pane.partition })
    }));
    toast(data.message);
  } catch (error) { toast(error.message, true); }
}

function triggerImageDownload(url) {
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  link.hidden = true;
  document.body.append(link);
  link.click();
  setTimeout(() => link.remove(), 1000);
}

function showDownloadReady(image, url) {
  modal.classList.remove("busy", "failed");
  showModal(`
    <div class="modal-heading"><span class="modal-kicker">SAVE IMAGE</span><h2>Your download is ready</h2></div>
    <p>The timestamped ZIP contains <strong>${esc(image.name)}</strong> and a technical README.</p>
    <div class="help-note"><strong>Did the automatic download not appear?</strong> Select Download ZIP below. This direct link remains available until you close this message.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Close</button><a class="button primary download-ready-link" href="${esc(url)}" download>Download ZIP</a></div>
  `, null, { replace: modal.open });
  modalContent.querySelector(".download-ready-link").onclick = () => {
    toast("Download requested. Check the browser download list if it does not appear immediately.");
  };
}

function applySavedImageSummary(image) {
  panes.forEach((candidate, candidateIndex) => {
    if (candidate.image?.id !== image.id) return;
    candidate.image = image;
    renderPane(candidateIndex, true);
  });
}

async function saveImage(index) {
  const pane = panes[index];
  const existingDialog = modal.open;
  try {
    if (!existingDialog) {
      showModal('<div class="analysis-loading"><span class="modal-progress-icon">↻</span><h2>Preparing download</h2></div>');
      modal.classList.add("busy");
      setModalProgress({
        title: "Preparing image download",
        message: "Starting hardware and filesystem checks…",
        details: [
          { label: "Stages", value: "Validate, checksum, index, then build the complete ZIP" },
          { label: "Ready means ready", value: "The download starts only after the ZIP has finished building" },
        ],
      }, 0, 100);
    }
    const data = await trackedPaneOperation(
      index,
      "Validating image before download…",
      operationId => api(`/api/images/${pane.image.id}/download/prepare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operationId }),
      })
    );
    if (!existingDialog && modal.open) {
      setModalProgress({
        title: "Download ZIP complete",
        message: "The complete timestamped ZIP is ready for the browser.",
        details: [{ label: "Status", value: "Checksums, README and every image file are included" }]
      }, 100, 100);
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    applySavedImageSummary(data.image);
    const downloadUrl = `/api/images/${pane.image.id}/download`;
    triggerImageDownload(downloadUrl);
    if (!existingDialog) showDownloadReady(pane.image, downloadUrl);
    toast("Complete timestamped image and README ZIP download started.");
    return true;
  } catch (error) {
    if (!existingDialog && modal.open) modal.close();
    toast(`Could not save ${pane.image.name}: ${error.message}`, true);
    return false;
  }
}

function exportImageAs(index) {
  const pane = panes[index];
  const formats = pane.image.exportFormats || [];
  if (!formats.length) {
    toast("This image has no compatible export formats.", true);
    return;
  }
  showModal(`
    <h2>Export image as…</h2>
    <p>Convert the current decoded sectors of <strong>${esc(pane.image.name)}</strong> into another compatible container. The working image is left unchanged; a new file downloads separately from the usual Save ZIP.</p>
    <div class="field"><label>Target format</label><select name="format">
      ${formats.map(entry => `<option value="${esc(entry.format)}">${esc(entry.label)}</option>`).join("")}
    </select></div>
    <div class="help-note">HFE and SCP exports are verified by decoding the result again and comparing it byte-for-byte with the current sectors before the download starts.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="export">Export</button></div>`,
  async form => {
    const format = form.get("format");
    const entry = formats.find(candidate => candidate.format === format);
    await paneOperation(index, "Encoding and verifying the export…", async () => {
      const response = await fetch(`/api/images/${pane.image.id}/export?${new URLSearchParams({ format })}`);
      if (!response.ok) {
        const row = await response.json().catch(() => ({}));
        throw new Error(row.error || "Export failed");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${pathNameWithoutExtension(pane.image.name)}-export.${entry?.extension || format}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return { image: pane.image };
    });
    toast(`Export to ${entry?.label || format} complete.`);
  });
}

async function recoverPreviousSession(index) {
  try {
    const data = await api("/api/images/recoverable");
    const openIds = new Set(panes.map(pane => pane.image?.id).filter(Boolean));
    const recoverable = data.images.filter(image => !openIds.has(image.id));
    const options = recoverable.map((image, position) => {
      const modified = new Date(image.modified).toLocaleString();
      const selected = position === 0 ? " selected" : "";
      return `<option value="${esc(image.id)}"${selected}>${esc(image.name)} · ${esc(humanSize(image.size))} · ${esc(modified)}</option>`;
    }).join("");
    const emptyMessage = recoverable.length
      ? ""
      : '<div class="help-note no-recovery-sessions">No previous sessions belonging to this browser are currently available.</div>';
    const modalClosed = showModal(`
      <h2>Recover previous session</h2>
      <p>Only working images owned by this browser are shown. The newest available session is selected first.</p>
      ${emptyMessage}
      <div class="field"><label>Saved working session</label><select name="imageId" ${recoverable.length ? "" : "disabled"}>${options}</select></div>
      <div class="modal-actions recovery-actions">
        <button class="button danger clear-selected-session" type="button" ${recoverable.length ? "" : "disabled"}>Clear selected</button>
        <button class="button danger clear-all-sessions" type="button" ${recoverable.length ? "" : "disabled"}>Clear all previous</button>
      </div>
      <div class="help-note">Recovery reopens the server-side working copy with all completed changes. Clearing permanently deletes only the selected browser-owned working copies, never your original host files.</div>
      <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary recover-session" value="recover" ${recoverable.length ? "" : "disabled"}>Recover session</button></div>
    `, async form => {
      const imageId = form.get("imageId");
      const restored = await api(`/api/images/${encodeURIComponent(imageId)}`);
      await acceptImage(index, restored.image);
      toast(`${restored.image.name} recovered with its working changes.`);
    });
    const sessionSelect = modalContent.querySelector('select[name="imageId"]');
    const recoverButton = modalContent.querySelector(".recover-session");
    const clearSelected = modalContent.querySelector(".clear-selected-session");
    const clearAll = modalContent.querySelector(".clear-all-sessions");
    const updateRecoveryControls = () => {
      const hasSessions = sessionSelect.options.length > 0;
      sessionSelect.disabled = !hasSessions;
      recoverButton.disabled = !hasSessions;
      clearSelected.disabled = !hasSessions;
      clearAll.disabled = !hasSessions;
      modalContent.querySelector(".no-recovery-sessions")?.toggleAttribute("hidden", hasSessions);
    };
    clearSelected.addEventListener("click", async () => {
      const option = sessionSelect.selectedOptions[0];
      if (!option || !await confirmChoice("Clear this working copy?", `“${option.textContent}” will be removed permanently.`, { confirmLabel: "Clear working copy", danger: true })) return;
      clearSelected.disabled = true;
      try {
        await api("/api/images/recoverable", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ imageIds: [option.value] })
        });
        option.remove();
        updateRecoveryControls();
        toast("Previous working session cleared.");
      } catch (error) {
        toast(`Could not clear the session: ${error.message}`, true);
        updateRecoveryControls();
      }
    });
    clearAll.addEventListener("click", async () => {
      const imageIds = [...sessionSelect.options].map(option => option.value);
      if (!imageIds.length || !await confirmChoice("Clear every previous session?", `All ${imageIds.length} working session${imageIds.length === 1 ? "" : "s"} shown here will be removed permanently.`, { confirmLabel: "Clear them all", danger: true })) return;
      clearAll.disabled = true;
      try {
        const result = await api("/api/images/recoverable", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ imageIds })
        });
        sessionSelect.replaceChildren();
        updateRecoveryControls();
        toast(`${result.removed} previous working session${result.removed === 1 ? "" : "s"} cleared.`);
      } catch (error) {
        toast(`Could not clear the sessions: ${error.message}`, true);
        updateRecoveryControls();
      }
    });
    await modalClosed;
  } catch (error) {
    toast(`Could not recover a session: ${error.message}`, true);
  }
}

function downloadFile(index, name, pathOverride = null) {
  const pane = panes[index];
  if (pane.archivePath) {
    window.location.href = archiveMemberUrl(pane, name);
    return;
  }
  const query = new URLSearchParams({ path: pathOverride || fullPath(pane.path, name), bundle: "metadata" });
  if (pane.partition !== null) query.set("partition", pane.partition);
  if (pane.side !== null) query.set("side", pane.side);
  window.location.href = `/api/images/${pane.image.id}/file?${query}`;
}

const ONLINE_MACHINES = [
  ["all", "All compatible machines"],
  ["st", "Atari ST"], ["megast", "Atari Mega ST"], ["ste", "Atari STE"],
  ["megaste", "Atari Mega STE"], ["tt030", "Atari TT030"], ["falcon030", "Atari Falcon030"],
];
const ONLINE_MACHINE_STORAGE_KEY = "atari-file-forge-online-machine";
const ACTIVE_PROFILE_STORAGE_KEY = "atari-file-forge-active-hardware-profile";

function storedOnlineMachine() {
  try {
    const value = persistentStorage.getItem(ONLINE_MACHINE_STORAGE_KEY) || "";
    return ONLINE_MACHINES.some(([machine]) => machine === value) ? value : "";
  } catch (_error) {
    return "";
  }
}

function rememberOnlineMachine(value) {
  if (ONLINE_MACHINES.some(([machine]) => machine === value)) {
    persistentStorage.setItem(ONLINE_MACHINE_STORAGE_KEY, value);
  }
}

function onlineMachineFromProfile(profile = {}) {
  const configured = String(profile.catalogMachine || "").toLowerCase();
  if (ONLINE_MACHINES.some(([value]) => value === configured)) return configured;
  const profileMachine = String(profile.machine || "").toLowerCase();
  const match = ONLINE_MACHINES.find(([value]) => value !== "all" && profileMachine.includes(value));
  return match ? match[0] : "";
}

function activeWorkbenchProfile(profiles = storedHardwareProfiles()) {
  const requested = Number.parseInt(persistentStorage.getItem(ACTIVE_PROFILE_STORAGE_KEY) || "0", 10);
  const index = Number.isInteger(requested) && requested >= 0 && requested < profiles.length
    ? requested
    : 0;
  return { index, profile: profiles[index] || BUILTIN_PROFILES[0] };
}

function setActiveWorkbenchProfile(index, profile) {
  persistentStorage.setItem(ACTIVE_PROFILE_STORAGE_KEY, String(index));
  rememberOnlineMachine(onlineMachineFromProfile(profile) || "all");
}

function defaultOnlineMachine(pane) {
  const profileMachine = onlineMachineFromProfile(pane.image?.hardwareProfile);
  if (profileMachine) return profileMachine;
  const workbenchProfileMachine = onlineMachineFromProfile(activeWorkbenchProfile().profile);
  if (workbenchProfileMachine) return workbenchProfileMachine;
  const workbenchMachine = storedOnlineMachine();
  if (workbenchMachine) return workbenchMachine;
  return "all";
}

async function showOnlineSources(index) {
  const data = await api("/api/catalog/sources");
  const rows = data.sources.map((source, offset) => `<fieldset class="online-source-row" data-source="${offset}">
    <label class="check"><input type="checkbox" name="enabled-${offset}" ${source.enabled ? "checked" : ""}> Enabled</label>
    <label>Name<input name="name-${offset}" value="${esc(source.name)}" required></label>
    <label>Catalogue URL<input name="url-${offset}" type="url" value="${esc(source.url)}" required></label>
    <label>Machines<input name="machines-${offset}" value="${esc(source.machines.join(","))}" placeholder="st,ste,falcon030"></label>
    <label class="online-provider-options">Provider settings (JSON)<textarea name="options-${offset}" rows="5">${esc(JSON.stringify(source.options || {}, null, 2))}</textarea></label>
    <input type="hidden" name="id-${offset}" value="${esc(source.id)}"><input type="hidden" name="type-${offset}" value="${esc(source.type)}">
    <input type="hidden" name="direct-${offset}" value="${source.direct ? "1" : "0"}">
  </fieldset>`).join("");
  const closed = showModal(`<div class="modal-heading"><span class="modal-kicker">ONLINE LIBRARY</span><h2>Catalogue sources</h2><p>Enable, disable or relocate a provider. Provider settings contain its query templates, categories and machine IDs, so site changes can be handled without changing application code.</p></div>
    <div class="online-source-list">${rows}</div>
    <fieldset class="online-new-source"><legend>Add a compatible provider</legend><label>Name<input name="newName" placeholder="My Atari archive"></label><label>URL<input name="newUrl" type="url" placeholder="https://…"></label><label>Loading strategy<select name="newLoader"><option value="page">Single page</option><option value="category-crawl">Category crawl</option><option value="machine-index">Machine indexes</option></select></label><label>Page layout<select name="newParser"><option value="thumbnail-cards">Thumbnail cards</option><option value="section-catalogue">Section catalogue</option><option value="function-calls">Function-call records</option><option value="item-rows">Linked item rows</option><option value="query-media-tiles">Media links in query parameters</option><option value="html-cards">Configurable HTML cards</option><option value="zip-links">ZIP download links</option><option value="package-paragraphs">Package paragraphs</option><option value="links">Plain links</option></select></label><label>Machines<input name="newMachines" placeholder="st,ste,falcon030"></label><label class="online-provider-options">Provider settings (JSON)<textarea name="newOptions" rows="5">{}</textarea></label></fieldset>
    <div class="modal-actions"><button class="button" type="button" data-back-library>Back</button><button class="button primary" type="submit">Save sources</button></div>`, async form => {
      const sources = data.sources.map((source, offset) => ({
        id: form.get(`id-${offset}`), name: form.get(`name-${offset}`), url: form.get(`url-${offset}`),
        type: form.get(`type-${offset}`), machines: String(form.get(`machines-${offset}`) || "").split(",").map(value => value.trim()).filter(Boolean),
        direct: form.get(`direct-${offset}`) === "1", enabled: form.has(`enabled-${offset}`),
        options: JSON.parse(String(form.get(`options-${offset}`) || "{}"))
      }));
      if (form.get("newName") && form.get("newUrl")) sources.push({
        id: String(form.get("newName")).toLowerCase().replace(/[^a-z0-9]+/g, "-"), name: form.get("newName"),
        url: form.get("newUrl"), type: "configured", direct: true, enabled: true,
        machines: String(form.get("newMachines") || "all").split(",").map(value => value.trim()).filter(Boolean),
        options: { ...JSON.parse(String(form.get("newOptions") || "{}")), loader: form.get("newLoader"), parser: form.get("newParser") }
      });
      await api("/api/catalog/sources", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sources }) });
      toast("Online catalogue sources saved");
    }, { replace: true });
  modalContent.querySelector("[data-back-library]").onclick = () => {
    modal.close();
    setTimeout(() => showOnlineLibrary(index), 0);
  };
  return closed;
}

//: The media an Online Library result can arrive as. A badge is shown only
//: for a container the catalogue actually declares, so an unrecognised entry
//: says nothing rather than guessing.
const ONLINE_MEDIA_BADGES = Object.freeze({
  st: "ST", msa: "MSA", stx: "STX", dim: "DIM", hfe: "HFE", scp: "SCP", zip: "ZIP",
});

function onlineMediaBadges(item) {
  const declared = Array.isArray(item.media) ? item.media : [item.media, item.format, item.filename].filter(Boolean);
  const found = new Set();
  declared.forEach(value => {
    const text = String(value).toLowerCase();
    const extension = text.match(/\.([a-z0-9]+)$/)?.[1] || text;
    if (ONLINE_MEDIA_BADGES[extension]) found.add(ONLINE_MEDIA_BADGES[extension]);
  });
  return [...found].map(badge => `<small class="pill">${esc(badge)}</small>`).join("");
}

function nextAvailableOnlineDirectoryName(pane, title, usedNames) {
  const rule = targetNameRule(pane, title || "ONLINE");
  const base = rule.suggested || "ONLINE";
  let candidate = base;
  for (let suffix = 1; usedNames.has(candidate.toLowerCase()); suffix += 1) {
    const ending = String(suffix);
    candidate = `${base.slice(0, Math.max(1, rule.limit - ending.length))}${ending}`;
  }
  usedNames.add(candidate.toLowerCase());
  return candidate;
}

async function planOnlineDirectories(index, items, targetPath) {
  const pane = panes[index];
  const listing = targetPath === pane.path
    ? { entries: pane.entries }
    : await api(`/api/images/${pane.image.id}/tree?${new URLSearchParams({ path: targetPath })}`);
  const usedNames = new Set((listing.entries || []).map(entry => String(entry.name || "").toLowerCase()));
  return new Map(items.map(item => [
    item.id,
    nextAvailableOnlineDirectoryName(pane, item.title, usedNames),
  ]));
}

async function showOnlineLibrary(index) {
  const pane = panes[index];
  const machine = defaultOnlineMachine(pane);
  const machineOptions = ONLINE_MACHINES.map(([value, label]) => `<option value="${value}" ${value === machine ? "selected" : ""}>${label}</option>`).join("");
  let acceptedOnlineSignature = "";
  let acceptedOnlineDirectoryNames = new Map();
  showModal(`<div class="modal-heading online-library-heading"><span class="modal-kicker">ONLINE LIBRARY</span><h2>Find software to install</h2><p>Search trusted Atari archives, select several results, then install them through the same checked workflow as local files.</p></div>
    <div class="online-search-bar"><label>Machine<select name="machine">${machineOptions}</select></label><label class="online-query">Title, publisher or keyword<input name="query" type="search" placeholder="Leave blank to browse"></label><label>Show<select name="scope"><option value="missing">Not already present</option><option value="all">All results</option></select></label><button class="button online-search" type="button">Search</button><button class="button ghost online-sources" type="button">Sources…</button></div>
    <div class="online-status">Choose a machine and search the configured catalogues.</div>
    <div class="online-results" aria-live="polite"></div>
    <div class="online-install-options">
      <label class="check"><input type="checkbox" name="createDirectory" checked> Create a folder for each downloaded item</label><span class="field-note">Each item is installed into its own folder beneath the current one unless this is unticked.</span>
    </div>
    <div class="online-compatibility-review" aria-live="polite"></div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary online-install" type="submit" disabled>Install selected</button></div>`, async form => {
      const itemIds = form.getAll("catalogItem");
      if (!itemIds.length) { toast("Select one or more downloadable items first.", true); return false; }
      const signature = JSON.stringify({
        itemIds,
        createDirectory: form.has("createDirectory"),
      });
      if (acceptedOnlineSignature !== signature) {
        const selectedItems = itemIds.map(id => resultItems.find(item => item.id === id)).filter(Boolean);
        const targetPath = pane.path;
        const createDirectories = form.has("createDirectory");
        const directoryNames = createDirectories
          ? await planOnlineDirectories(index, selectedItems, targetPath)
          : new Map();
        const report = await requestCompatibilityReport(
          index,
          "online-library-install",
          "online-catalogue",
          selectedItems.map(item => ({
            name: createDirectories
              ? directoryNames.get(item.id)
              : targetPath || item.title || item.filename || "Software",
            sourceName: item.title || item.filename || "Software",
            nameIsLeaf: true,
            existingDestination: !createDirectories,
            source: item.sourceName || item.pageUrl || "Online Library",
            type: createDirectories ? "directory" : "contents into folder",
            allowDuplicateName: !createDirectories,
          })),
        );
        const reviewHost = modalContent.querySelector(".online-compatibility-review");
        reviewHost.innerHTML = `<details open><summary>Compatibility preflight · ${esc(report.summary)}</summary>
          <div class="preflight-list">${report.items.map(item => `<article><b>${item.index + 1}</b><span><strong>${esc(item.sourceName)}${item.targetName !== item.sourceName ? ` → ${esc(item.targetName)}` : ""}</strong>${[...item.conversions, ...item.losses].map(note => `<em>${esc(note)}</em>`).join("")}</span></article>`).join("")}</div>
          <div class="finding-list">${report.issues.map(item => `<p class="finding ${esc(item.severity)}"><b>${esc(item.severity)}</b>${esc(item.message)}</p>`).join("") || '<p class="finding pass"><b>ready</b>No conversion loss or blocking clash was detected.</p>'}</div>
          ${report.canProceed ? "" : '<button class="button online-revise" type="button">Change selection or import options</button>'}</details>`;
        acceptedOnlineSignature = report.canProceed ? signature : "";
        acceptedOnlineDirectoryNames = report.canProceed ? directoryNames : new Map();
        const install = modalContent.querySelector(".online-install");
        install.textContent = report.canProceed ? `Install ${itemIds.length} reviewed item${itemIds.length === 1 ? "" : "s"}` : "Blocked by compatibility findings";
        reviewHost.querySelector(".online-revise")?.addEventListener("click", () => {
          acceptedOnlineSignature = "";
          acceptedOnlineDirectoryNames = new Map();
          reviewHost.innerHTML = "";
          install.textContent = "Install selected";
          install.disabled = !resultHost.querySelector('[name="catalogItem"]:checked');
          modalContent.querySelector('[name="createDirectory"], [name="catalogItem"]:checked')?.focus();
        });
        setTimeout(() => { install.disabled = !report.canProceed; }, 0);
        return false;
      }
      const titles = new Map([...modalContent.querySelectorAll('[name="catalogItem"]')].map(input => [input.value, input.closest("tr")?.querySelector("strong")?.textContent || input.value]));
      const results = [];
      let abortRequested = false;
      setModalAbort(async () => { abortRequested = true; setModalProgress({ title: "Stopping Online Library install", message: "The current item will finish safely, then no further downloads will start." }, results.length, itemIds.length); });
      for (let offset = 0; offset < itemIds.length; offset += 1) {
        if (abortRequested) break;
        const itemId = itemIds[offset];
        setModalProgress({ title: "Installing online software", message: `Downloading and checking ${titles.get(itemId)}…`, details: [{ label: "Destination", value: pane.path || pane.image.name }] }, offset, itemIds.length);
        try {
          const result = await api(`/api/images/${pane.image.id}/catalog/install`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ itemIds: [itemId], path: pane.path, partition: pane.partition, side: pane.side, identify: true, createDirectory: form.has("createDirectory"), directoryName: acceptedOnlineDirectoryNames.get(itemId) || "" })
          });
          pane.image = result.image;
          results.push(...result.items);
        } catch (error) {
          results.push({ id: itemId, title: titles.get(itemId), error: error.message });
        }
      }
      await acceptImage(index, pane.image);
      const successes = results.filter(item => !item.error);
      const failures = results.filter(item => item.error);
      toast(`${successes.length} online item${successes.length === 1 ? "" : "s"} installed${abortRequested ? " before the operation was stopped" : ""}`);
      failures.forEach(item => toast(`${item.title}: ${item.error}`, true));
    });

  const searchButton = modalContent.querySelector(".online-search");
  const installButton = modalContent.querySelector(".online-install");
  const resultHost = modalContent.querySelector(".online-results");
  const status = modalContent.querySelector(".online-status");
  let resultItems = [];
  let resultFailures = [];
  let resultContinuation = {};
  let resultHiddenInstalled = 0;
  let resultSort = { key: "title", direction: "asc" };
  const renderOnlineResults = () => {
    const selected = new Set([...resultHost.querySelectorAll('[name="catalogItem"]:checked')].map(input => input.value));
    const direction = resultSort.direction === "asc" ? 1 : -1;
    const items = [...resultItems].sort((left, right) => {
      const compared = String(left[resultSort.key] || "").localeCompare(String(right[resultSort.key] || ""), undefined, { numeric: true, sensitivity: "base" });
      return compared * direction || String(left.title || "").localeCompare(String(right.title || ""), undefined, { sensitivity: "base" });
    });
    const heading = (label, key) => {
      const active = resultSort.key === key;
      const arrow = active ? (resultSort.direction === "asc" ? "↑" : "↓") : "";
      const ariaSort = active ? (resultSort.direction === "asc" ? "ascending" : "descending") : "none";
      return `<th aria-sort="${ariaSort}"><button class="online-sort" type="button" data-sort="${key}">${label}<span aria-hidden="true">${arrow}</span></button></th>`;
    };
    resultHost.innerHTML = items.length ? `<table class="online-result-table" aria-label="Downloadable Atari software"><thead><tr><th></th>${heading("Title", "title")}${heading("Publisher", "publisher")}${heading("Year", "year")}${heading("Source", "sourceName")}<th></th></tr></thead><tbody>${items.map(item => `<tr class="${item.installed ? "already-installed" : ""}"><td><input type="checkbox" name="catalogItem" value="${esc(item.id)}" aria-label="Select ${esc(item.title)}" ${selected.has(item.id) ? "checked" : ""}></td><td><strong>${esc(item.title)}</strong>${item.version ? `<small>Version ${esc(item.version)}</small>` : ""}${item.description ? `<small>${esc(item.description)}</small>` : ""}</td><td>${esc(item.publisher || "Unknown")}</td><td>${esc(item.year || "-")}</td><td><span class="pill">${esc(item.sourceName)}</span>${onlineMediaBadges(item)}${item.installed ? '<small class="installed-label">Already present</small>' : ""}</td><td><a class="button tiny" href="${esc(item.pageUrl)}" target="_blank" rel="noopener">Details</a></td></tr>`).join("")}</tbody></table>` : '<div class="empty-list">No matching downloadable items were found. Try All results, another machine, or a broader search.</div>';
    if (Object.keys(resultContinuation).length) {
      resultHost.insertAdjacentHTML("beforeend", '<div class="online-load-more"><button class="button" type="button" data-online-more>Find more downloadable results</button><small>Only entries with verified downloadable Atari media are added.</small></div>');
      resultHost.querySelector("[data-online-more]").onclick = event => runSearch(null, true, event.currentTarget);
    }
    if (resultFailures.length) resultHost.insertAdjacentHTML("beforeend", `<details class="online-failures"><summary>Unavailable sources</summary>${resultFailures.map(item => `<p><b>${esc(item.source)}</b>: ${esc(item.error)}</p>`).join("")}</details>`);
    resultHost.querySelectorAll("[data-sort]").forEach(button => button.onclick = () => {
      const key = button.dataset.sort;
      resultSort = { key, direction: resultSort.key === key && resultSort.direction === "asc" ? "desc" : "asc" };
      renderOnlineResults();
    });
    resultHost.querySelectorAll('[name="catalogItem"]').forEach(input => input.onchange = () => {
      acceptedOnlineSignature = "";
      modalContent.querySelector(".online-compatibility-review").innerHTML = "";
      installButton.textContent = "Install selected";
      installButton.disabled = !resultHost.querySelector('[name="catalogItem"]:checked');
    });
    installButton.disabled = !resultHost.querySelector('[name="catalogItem"]:checked');
  };
  const runSearch = async (requestedMachine = null, append = false, moreButton = null) => {
    searchButton.disabled = true; installButton.disabled = true;
    if (moreButton) {
      moreButton.disabled = true;
      moreButton.textContent = "Checking the next catalogue page…";
    }
    status.textContent = append ? "Checking more catalogue entries for downloadable media…" : "Contacting enabled catalogues…";
    if (!append) resultHost.innerHTML = '<div class="online-loading">Searching the Online Library…</div>';
    try {
      const parameters = new URLSearchParams({ q: modalContent.querySelector('[name="query"]').value, machine: requestedMachine || modalContent.querySelector('[name="machine"]').value, scope: modalContent.querySelector('[name="scope"]').value, path: pane.path });
      if (pane.partition !== null) parameters.set("partition", pane.partition);
      if (append) parameters.set("cursor", JSON.stringify(resultContinuation));
      const data = await api(`/api/images/${pane.image.id}/catalog/search?${parameters}`);
      const collectionTitles = new Set();
      if (collectionCatalogue.available) {
        try {
          (await collectionCatalogue.list()).forEach(image => (image.titles || []).forEach(title => collectionTitles.add(title.key)));
        } catch (_error) { /* Online search remains usable if IndexedDB is unavailable. */ }
      }
      const incoming = data.items.filter(item => item.downloadable).map(item => ({
        ...item,
        installed: item.installed || collectionTitles.has(window.AtariCollectionCatalogue.titleKey(item.title)),
      }));
      resultItems = append
        ? [...new Map([...resultItems, ...incoming].map(item => [item.id, item])).values()]
        : incoming;
      resultFailures = append ? [...resultFailures, ...data.failures] : data.failures;
      resultContinuation = data.continuation || {};
      resultHiddenInstalled = (append ? resultHiddenInstalled : 0) + Number(data.hiddenInstalled || 0);
      resultSort = { key: "title", direction: "asc" };
      status.textContent = `${resultItems.length} verified downloadable result${resultItems.length === 1 ? "" : "s"}${resultHiddenInstalled ? ` · ${resultHiddenInstalled} installed result${resultHiddenInstalled === 1 ? "" : "s"} hidden` : ""}${Object.keys(resultContinuation).length ? " · more catalogue entries are available to check" : " · all matching catalogue entries checked"}${resultFailures.length ? ` · ${resultFailures.length} source${resultFailures.length === 1 ? "" : "s"} unavailable` : ""}`;
      renderOnlineResults();
    } catch (error) {
      status.textContent = "Search failed"; resultHost.innerHTML = `<div class="help-warning">${esc(error.message)}</div>`;
    } finally { searchButton.disabled = false; }
  };
  searchButton.onclick = () => runSearch();
  modalContent.querySelector(".online-sources").onclick = () => showOnlineSources(index);
  modalContent.querySelector('[name="query"]').onkeydown = event => { if (event.key === "Enter") { event.preventDefault(); runSearch(); } };
  runSearch(machine);
}

function wireBatchMatchSelectors(entries) {
  modalContent.querySelectorAll(".batch-match").forEach(select => {
    select.onchange = () => {
      if (select.value === "") return;
      const offset = Number(select.dataset.offset);
      const match = entries[offset]?.matches?.[Number(select.value)];
      if (!match) return;
      modalContent.querySelector(`[name="title-${offset}"]`).value = match.title;
      modalContent.querySelector(`[name="publisher-${offset}"]`).value = match.publisher;
    };
  });
}

function compactImage(index) {
  const pane = panes[index];
  const supportsOrder = pane.image.kind === "gemdos" || pane.image.kind === "hd";
  showModal(`
    <h2>Compact this filesystem?</h2>
    <p>Files will be reorganised into contiguous low sectors and free space consolidated. The operation is performed only on the working copy.</p>
    ${supportsOrder ? '<div class="field"><label>Place these paths first (optional, comma separated)</label><input name="order" placeholder="AUTO\\HDDRIVER.PRG,DESKTOP.INF"></div>' : ""}
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="compact">Compact</button></div>`,
  async form => {
    const data = await paneOperation(index, "Compacting filesystem…", () => api(`/api/images/${pane.image.id}/compact`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ partition: pane.partition, order: supportsOrder ? (form.get("order") || null) : null })
    }));
    pane.image = data.image;
    await loadDirectory(index);
    toast(data.message);
  });
}

//: A floppy container holds the sectors of one disk in its own packing, so
//: converting it writes those same sectors into another container. A track
//: this build cannot unpack stops the conversion rather than producing a disk
//: with a hole in it.
function convertContainer(index) {
  const pane = panes[index];
  const defaultTarget = preferredDestinationPane(index);
  const readOnly = pane.image.kind === "stx";
  showModal(`
    <h2>Convert ${esc(CONTAINER_LABELS[pane.image.kind] || "this container")}</h2>
    <p>The container holds a whole floppy, so every sector is written back at the track and side it came from and the result is the disk the container was made from.${readOnly ? " A Pasti capture records what the controller saw, including protection a sector image cannot hold, so what comes out is the readable part of the disk and not the disk itself." : ""}</p>
    <div class="field"><label>Destination format</label><select name="format">
      <option value="st">ST · plain sectors, the format every tool reads</option>
      <option value="msa">MSA · the same sectors, packed track by track</option>
      <option value="dim">DIM · FastCopy Pro, sectors behind a small header</option>
    </select></div>
    <div class="field"><label>Open the converted disk in</label><select name="targetPane">
      ${otherPaneIndexes(index).map(offset => `<option value="${offset}" ${offset === defaultTarget ? "selected" : ""}>${esc(paneLabel(offset))}</option>`).join("")}
    </select><small>An empty pane is preferred. Replacing an edited pane requires confirmation.</small></div>
    ${readOnly ? '<div class="help-warning"><strong>A Pasti capture is read-only.</strong> Protection that depends on fuzzy bytes, sector timing or duplicate sector identifiers cannot be written into a sector image, so a converted copy will not satisfy a protection check the original passes.</div>' : ""}
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="convert">Convert container</button></div>`,
  async form => {
    const targetIndex = Number(form.get("targetPane"));
    if (!otherPaneIndexes(index).includes(targetIndex)) throw new Error("Choose another pane for the converted disk.");
    if (panes[targetIndex].image?.dirty && !await confirmChoice(
      "Replace an edited image?",
      `${paneLabel(targetIndex)} has changes that have not been downloaded.`,
      { confirmLabel: "Replace it", danger: true, note: "Its recoverable session is kept, so it can be reopened from Recover previous session." },
    )) return false;
    const data = await paneOperation(index, "Rebuilding the disk from its stored tracks…", () => api(`/api/images/${pane.image.id}/convert`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format: form.get("format") })
    }));
    await acceptImage(targetIndex, data.image);
    const tracks = data.files || [];
    toast(`${tracks.length} track${tracks.length === 1 ? "" : "s"} rebuilt as ${form.get("format").toUpperCase()}`);
  });
}

function containerTrackRows(tracks, comparison = false) {
  return (tracks || []).map(track => `<tr class="${track.changed ? "changed" : ""}">
    <td>${Number(track.index) + 1}</td><td><code>${esc(track.id)}</code></td>
    <td>${esc(track.kind || (track.changed ? "Repacked track" : "Preserved track"))}</td>
    <td>${Number(track.length).toLocaleString()} B</td>
    <td>${comparison ? (track.changed ? "Data and checksum changed" : "Byte-identical") : (track.preserved ? "Preserved" : "Review")}</td>
  </tr>`).join("");
}

function containerStructuralReview(proof) {
  return new Promise(resolve => {
    const shade = document.createElement("div");
    shade.className = "editor-choice-shade";
    shade.setAttribute("role", "dialog");
    shade.setAttribute("aria-modal", "true");
    const changed = (proof.tracks || proof.chunks || []).filter(track => track.changed).length;
    const tracks = proof.tracks || proof.chunks || [];
    shade.innerHTML = `<section class="editor-choice-card container-structural-review"><header><div><small>CONTAINER STRUCTURAL COMPARISON</small><h2>Review the proven rebuild</h2></div></header>
      <div class="help-note"><strong>${(proof.changedBlocks || []).length} block${(proof.changedBlocks || []).length === 1 ? "" : "s"} will change.</strong> ${esc(proof.proof)} Raw container length: ${proof.sameLength ? "unchanged" : "changed"}.</div>
      <div class="container-project-table"><table><thead><tr><th>#</th><th>Track</th><th>Meaning</th><th>Size</th><th>Result</th></tr></thead><tbody>${containerTrackRows(tracks, true)}</tbody></table></div>
      <p><strong>${changed}</strong> track${changed === 1 ? "" : "s"} changed. Every unlisted container property and every unchanged or unrecognised track remains byte-identical.</p>
      <div class="modal-actions"><button type="button" class="button ghost" data-choice="cancel">Cancel</button><button type="button" class="button primary" data-choice="save">Save the proven rebuild</button></div></section>`;
    const finish = value => { shade.remove(); resolve(value); };
    shade.querySelectorAll("[data-choice]").forEach(button => button.onclick = () => finish(button.dataset.choice));
    shade.onkeydown = event => { if (event.key === "Escape") finish("cancel"); else trapFocus(shade, event); };
    attachEditorOverlay(shade);
    shade.querySelector('[data-choice="cancel"]').focus();
  });
}

//: What a container project shows depends on what the container keeps. MSA
//: records each track's packed length, DIM its geometry header and its
//: used-sector map, and a Pasti capture the protection a sector image cannot
//: hold: fuzzy bytes, sector timing, duplicate or missing identifiers and
//: sectors that are not 512 bytes long.
function containerProjectSections(kind, project) {
  if (kind === "stx") {
    const rows = (project.protection?.tracks || []).map(track => `<tr>
      <td>${Number(track.track)}</td><td>${Number(track.side)}</td>
      <td>${Number(track.sectorCount ?? 0)}</td>
      <td>${track.fuzzyBytes ? `${Number(track.fuzzyBytes).toLocaleString()} fuzzy` : "-"}</td>
      <td>${track.timing ? "Recorded" : "-"}</td>
      <td>${esc((track.anomalies || []).join(", ") || "None")}</td>
    </tr>`).join("");
    const summary = project.protection || {};
    return `<div class="help-warning"><strong>A Pasti capture is read-only.</strong> It records what the floppy controller saw, so a sector image written from it loses whatever the protection depends on. Convert it to read the files; keep the capture to keep the disk.</div>
      <div class="operation-summary"><span><b>${Number(summary.fuzzyTracks ?? 0)}</b><small>Tracks with fuzzy bytes</small></span><span><b>${Number(summary.timedTracks ?? 0)}</b><small>Tracks with recorded timing</small></span><span><b>${Number(summary.duplicateIdentifiers ?? 0)}</b><small>Duplicate sector identifiers</small></span><span><b>${Number(summary.missingIdentifiers ?? 0)}</b><small>Missing sector identifiers</small></span><span><b>${Number(summary.nonStandardSizes ?? 0)}</b><small>Sectors that are not 512 bytes</small></span></div>
      <h3>Protection report</h3><div class="container-project-table"><table><thead><tr><th>Track</th><th>Side</th><th>Sectors</th><th>Fuzzy</th><th>Timing</th><th>Anomalies</th></tr></thead><tbody>${rows || '<tr><td colspan="6">No protection features were recorded in this capture.</td></tr>'}</tbody></table></div>`;
  }
  if (kind === "dim") {
    const rows = (project.tracks || []).map(track => `<tr>
      <td>${Number(track.track)}</td><td>${Number(track.side)}</td>
      <td>${Number(track.sectors ?? 0)}</td>
      <td>${Number(track.length ?? 0).toLocaleString()} B</td>
      <td>${track.used === false ? "Not in the used-sector map" : "Stored"}</td>
    </tr>`).join("");
    return `<div class="help-note"><strong>FastCopy Pro keeps a geometry header and a used-sector map.</strong> A track the map marks unused is not stored, so a rebuilt disk fills it with zeroes rather than inventing bytes.</div>
      <h3>Tracks</h3><div class="container-project-table"><table><thead><tr><th>Track</th><th>Side</th><th>Sectors</th><th>Length</th><th>Stored</th></tr></thead><tbody>${rows || '<tr><td colspan="5">No track table was recorded.</td></tr>'}</tbody></table></div>`;
  }
  const rows = (project.tracks || []).map(track => `<tr>
    <td>${Number(track.track)}</td><td>${Number(track.side)}</td>
    <td>${Number(track.packedLength ?? 0).toLocaleString()} B</td>
    <td>${Number(track.unpackedLength ?? 0).toLocaleString()} B</td>
    <td>${track.packed ? "Run-length packed with $E5" : "Stored whole"}</td>
  </tr>`).join("");
  return `<div class="help-note"><strong>Magic Shadow Archiver packs each track on its own.</strong> A track whose packed form would be no smaller is stored whole, which is why the two lengths often match.</div>
    <h3>Per-track packing</h3><div class="container-project-table"><table><thead><tr><th>Track</th><th>Side</th><th>Packed</th><th>Unpacked</th><th>Packing</th></tr></thead><tbody>${rows || '<tr><td colspan="5">No track table was recorded.</td></tr>'}</tbody></table></div>`;
}

async function showContainerProject(index) {
  const pane = panes[index];
  const kind = pane.image.kind;
  const label = CONTAINER_LABELS[kind] || "Floppy container";
  analysisLoading(`Reading the ${label.toLowerCase()}`, "Indexing every track and its checksums…");
  try {
    const project = await api(`/api/images/${pane.image.id}/container-project`);
    replaceAnalysisLoading(`<div class="analysis-dialog wide-analysis container-project-dialog"><header><div><small>LOSSLESS CONTAINER PROJECT · ${esc(String(kind).toUpperCase())} ${esc(project.version || "")}</small><h2>${esc(pane.image.name)}</h2></div><span>${esc(project.compressed ? "PACKED" : "STORED WHOLE")}</span></header>
      <div class="operation-summary"><span><b>${(project.tracks || []).length}</b><small>Tracks</small></span><span><b>${Number(project.sides ?? 0)}</b><small>Sides</small></span><span><b>${humanSize(project.rawLength || pane.image.size)}</b><small>Container bytes</small></span></div>
      ${(project.warnings || []).length ? `<div class="help-warning"><strong>Read before converting</strong>${project.warnings.map(warning => `<p>${esc(warning)}</p>`).join("")}</div>` : '<div class="help-note"><strong>Complete reconstruction:</strong> every stored track was decoded and its checksum verified, so the sectors can be written into another container without loss.</div>'}
      ${containerProjectSections(kind, project)}
      <div class="help-note"><strong>Project identity:</strong> <code>${esc(project.sha256)}</code></div><div class="modal-actions"><button class="button primary" value="cancel">Close</button></div></div>`);
  } catch (error) { toast(error.message, true); modal.close(); }
}

async function newImageFromFileMenu(index, initialFormat) {
  let targetIndex = panes.findIndex(pane => !pane.image);
  if (targetIndex < 0) targetIndex = addPane();
  if (targetIndex >= 0) {
    showCreateImageModal(targetIndex, { initialFormat, lockTarget: true });
  }
}

function showCreateImageModal(preferredIndex = null, options = {}) {
  const firstEmpty = panes.findIndex(pane => !pane.image);
  const defaultTarget = preferredIndex ?? (firstEmpty < 0 ? 0 : firstEmpty);
  const floppyOptions = FLOPPY_GEOMETRIES.map(geometry =>
    `<option value="${geometry.value}">${geometry.label} ${geometry.singleSided ? "single sided" : "double sided"}${geometry.value === "hd-1440k" ? " · high density" : ""}</option>`).join("");
  const gotekOptions = FLOPPY_GEOMETRIES
    .filter(geometry => geometry.hfe)
    .map(geometry => ({ value: geometry.hfe, label: geometry.label }))
    .filter((entry, position, all) => all.findIndex(item => item.value === entry.value) === position)
    .map(entry => `<option value="${entry.value}">HFE · ${entry.label} floppy</option>`).join("");
  showModal(`
    <h2>Create a blank image</h2>
    <p>The new image opens as an editable working copy and can be downloaded when ready.</p>
    <div class="field" ${options.lockTarget ? "hidden" : ""}><label>Open new image in</label><select name="targetPane">
      ${panes.map((_pane, index) => `<option value="${index}" ${index === defaultTarget ? "selected" : ""}>${esc(paneLabel(index))}</option>`).join("")}
    </select><small>An empty pane is preferred. Replacing an edited pane requires confirmation.</small></div>
    <div class="field"><label>Format</label><select name="format">
      <optgroup label="Floppy">
        ${floppyOptions}
      </optgroup>
      <optgroup label="Gotek and HxC">
        ${gotekOptions}
      </optgroup>
      <optgroup label="Hard drive">
        <option value="hd">Hard drive · AHDI or MBR partitions</option>
        <option value="volume">Bare volume · one FAT16 partition, no table</option>
      </optgroup>
      <optgroup label="ROM">
        <option value="rom">Blank ROM image · banked or custom</option>
        <option value="cartridge">Cartridge · 128 KiB with a header</option>
      </optgroup>
    </select></div>
    <div class="field"><label>Volume label</label><input name="title" maxlength="11" value="EMPTY" required><small data-title-help></small></div>
    <div class="field"><label>Image size</label><input name="capacity" value="720K" readonly></div>
    <label class="check-field" data-bootable-field><input type="checkbox" name="bootable" value="yes"> Write a boot sector this machine can start from</label>
    <div class="hard-drive-create-options" hidden>
      <div class="field"><label>Partitions</label><input name="hdPartitions" type="number" min="1" max="12" value="2"><small>Each becomes a drive letter, starting at C:.</small></div>
      <div class="field"><label>Partition scheme</label><select name="hdScheme">
        <option value="ahdi">AHDI · the table TOS and every hard-disk driver reads</option>
        <option value="mbr">MBR · read by HDDRIVER and by a PC card reader</option>
      </select></div>
    </div>
    <div class="rom-create-options" hidden>
      <div class="field"><label>ROM family</label><select name="romPlatform"><option value="tos">TOS ROM · 192 KiB, 256 KiB or 512 KiB</option><option value="cartridge">Cartridge · 128 KiB at &amp;FA0000</option><option value="custom">Custom expansion or diagnostic ROM</option></select></div>
      <div class="field"><label>Total image size in bytes</label><input name="romTotalSize" type="number" min="256" max="67108864" step="256" value="262144" required></div>
      <div class="field"><label>Bank size in bytes</label><input name="romBankSize" type="number" min="256" max="67108864" step="256" value="262144" required><small>262,144 is a 256 KiB TOS 1.04 or 2.06 ROM and 524,288 a 512 KiB TOS 3.06. A 128 KiB cartridge is 131,072.</small></div>
      <div class="field"><label>Initial contents</label><select name="romTemplate"><option value="blank">Erased bytes only</option><option value="tos">ROM header and checksum skeleton</option></select></div>
      <div class="field"><label>Erased byte</label><select name="romEraseByte"><option value="255">&FF</option><option value="0">&00</option></select></div>
      <div class="field"><label>Byte layout</label><select name="romLayout"><option value="linear">Linear / banked</option><option value="byte-interleaved-2">Two byte-wide chips</option><option value="byte-interleaved-4">Four byte-wide chips</option></select></div>
    </div>
    <div class="cartridge-create-options" hidden>
      <div class="field"><label>Cartridge application name</label><input name="cartridgeApplication" maxlength="24" value="NEW CARTRIDGE" required></div>
      <div class="help-note">Creates a valid 128 KiB cartridge around one <code>&amp;ABCDEF42</code> application header: the magic longword, the entry point, the flags and the name TOS shows. The ROM scan on a real machine will find the application. It does not create a bootable operating system.</div>
    </div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="create">Create image</button></div>`,
  async form => {
    const targetIndex = options.lockTarget ? defaultTarget : Number(form.get("targetPane"));
    if (!panes[targetIndex]) throw new Error("Choose a valid destination pane.");
    if (panes[targetIndex].image?.dirty && !await confirmChoice(
      "Replace an edited image?",
      `${paneLabel(targetIndex)} has changes that have not been downloaded.`,
      { confirmLabel: "Replace it", danger: true, note: "Its recoverable session is kept, so it can be reopened from Recover previous session." },
    )) return false;
    const chosenFormat = form.get("format");
    const data = await api("/api/images/create", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        format: chosenFormat,
        title: form.get("title") || "EMPTY",
        capacity: form.get("capacity"),
        bootable: form.get("bootable") === "yes",
        targetHardware: createTargetMedia(chosenFormat),
        hardDisk: chosenFormat === "hd" ? {
          partitions: Number(form.get("hdPartitions")),
          scheme: form.get("hdScheme"),
        } : undefined,
        rom: chosenFormat === "rom" ? {
          platform: form.get("romPlatform"),
          totalSize: Number(form.get("romTotalSize")),
          bankSize: Number(form.get("romBankSize")),
          template: form.get("romTemplate"),
          eraseByte: Number(form.get("romEraseByte")),
          layout: form.get("romLayout"),
        } : chosenFormat === "cartridge" ? {
          platform: "cartridge",
          application: form.get("cartridgeApplication"),
        } : undefined,
      })
    });
    await acceptImage(targetIndex, data.image);
    toast(`${data.image.name} created`);
  });
  const format = modalContent.querySelector('select[name="format"]');
  if (options.initialFormat && [...format.options].some(option => option.value === options.initialFormat)) format.value = options.initialFormat;
  const capacity = modalContent.querySelector('input[name="capacity"]');
  const capacityLabel = capacity.closest(".field").querySelector("label");
  const title = modalContent.querySelector('input[name="title"]');
  const titleLabel = title.closest(".field").querySelector("label");
  const titleHelp = modalContent.querySelector("[data-title-help]");
  const bootableField = modalContent.querySelector("[data-bootable-field]");
  const bootable = modalContent.querySelector('input[name="bootable"]');
  // Every floppy format is FAT12 on a fixed geometry, so the size follows the
  // format and nothing else. A hard drive and a bare volume are sized by the
  // operator; a ROM is sized in its own section.
  const floppyProfiles = Object.fromEntries(FLOPPY_GEOMETRIES.flatMap(geometry => {
    const entry = { size: geometry.label, media: "floppy", bootable: true, hasTitle: true };
    return geometry.hfe ? [[geometry.value, entry], [geometry.hfe, entry]] : [[geometry.value, entry]];
  }));
  const profiles = {
    ...floppyProfiles,
    hd: { size: null, defaultCapacity: "256MB", media: "hd", bootable: true, hasTitle: true },
    volume: { size: null, defaultCapacity: "32MB", media: "volume", bootable: false, hasTitle: true },
    rom: { size: "Set below", media: "tos", bootable: false, hasTitle: true },
    cartridge: { size: "128K", media: "tos", bootable: false, hasTitle: true },
  };
  // A format the client does not know about is still openable: fall back to a
  // plain 720K double-sided floppy rather than throwing while building the
  // dialog.
  const profileFor = value => profiles[value] || floppyProfiles["ds-720k"];
  const capacities = new Map();
  let diskTitle = title.value;
  let previousFormat = format.value;
  const updateFormatControls = () => {
    const previousProfile = profileFor(previousFormat);
    if (previousProfile && !previousProfile.size) capacities.set(previousFormat, capacity.value);
    if (!title.disabled) diskTitle = title.value;

    const profile = profileFor(format.value);
    capacity.readOnly = Boolean(profile.size);
    capacity.value = profile.size || capacities.get(format.value) || profile.defaultCapacity;
    capacity.placeholder = profile.size ? "" : profile.defaultCapacity;
    capacityLabel.textContent = profile.size ? "Image size" : "Drive capacity";

    const hasTitle = profile.hasTitle !== false;
    title.disabled = !hasTitle;
    title.required = hasTitle;
    title.value = hasTitle ? diskTitle : "";
    titleLabel.textContent = ["rom", "cartridge"].includes(format.value)
      ? "ROM filename and title"
      : "Volume label";
    titleHelp.textContent = "Stored in the boot sector as the volume label. A GEMDOS label holds eleven characters.";
    title.maxLength = ["rom", "cartridge"].includes(format.value) ? 24 : 11;

    bootableField.hidden = !profile.bootable;
    if (!profile.bootable) bootable.checked = false;
    modalContent.querySelector(".hard-drive-create-options").hidden = format.value !== "hd";
    modalContent.querySelector(".rom-create-options").hidden = format.value !== "rom";
    modalContent.querySelector(".cartridge-create-options").hidden = format.value !== "cartridge";
    if (["rom", "cartridge"].includes(format.value)) {
      capacityLabel.textContent = "ROM capacity";
      titleHelp.textContent = "Used as the filename and, for the header template, its initial ROM title.";
    }
    previousFormat = format.value;
  };
  format.addEventListener("change", updateFormatControls);
  updateFormatControls();
}

//: What a newly created image is meant to be, so the service validates it the
//: same way it would validate one that had been opened from a file.
function createTargetMedia(format) {
  if (format === "hd") return "hd";
  if (format === "volume") return "volume";
  if (["rom", "cartridge"].includes(format)) return "tos";
  return "floppy";
}

const PROFILE_STORAGE_KEY = "atari-file-forge-hardware-profiles";
const RECIPE_STORAGE_KEY = "atari-file-forge-import-recipes";

//: Twelve machines a person is likely to be working towards, built from the
//: add-on identifiers in app/hardware_profiles.py. Each one is a real
//: combination: the TOS release the machine shipped with or was upgraded to,
//: the memory it plausibly holds, the drive and storage fitted to it and the
//: driver that makes that storage bootable.
const BUILTIN_PROFILES = [
  { name: "520ST · TOS 1.04, single-sided drive", machine: "st", addons: ["tos-104", "ram-512k", "drive-a-ss", "monitor-colour", "tv-modulator", "auto-folder"], catalogMachine: "st", filingSystem: "fat12", targetHardware: "floppy", driverBuild: "none", page: "0", emulator: "hatari", debugger: "hatari-debug" },
  { name: "1040ST · TOS 1.04, two drives", machine: "st", addons: ["tos-104", "ram-1m", "drive-a-ds", "drive-b-external", "monitor-mono", "printer", "auto-folder"], catalogMachine: "st", filingSystem: "fat12", targetHardware: "floppy", driverBuild: "none", page: "0", emulator: "hatari", debugger: "hatari-debug" },
  { name: "Mega ST 2 · blitter and an ACSI Megafile", machine: "megast", addons: ["tos-104", "ram-2m", "drive-a-ds", "acsi-megafile", "driver-ahdi", "blitter", "monitor-mono", "midi", "auto-folder"], catalogMachine: "megast", filingSystem: "fat16", targetHardware: "hd", driverBuild: "ahdi", page: "0", emulator: "hatari", debugger: "hatari-debug" },
  { name: "520STE · TOS 1.62, colour monitor", machine: "ste", addons: ["tos-162", "ram-512k", "drive-a-ds", "monitor-colour", "auto-folder"], catalogMachine: "ste", filingSystem: "fat12", targetHardware: "floppy", driverBuild: "none", page: "0", emulator: "hatari", debugger: "hatari-debug" },
  { name: "1040STE · TOS 1.62, 4 MiB", machine: "ste", addons: ["tos-162", "ram-4m", "drive-a-ds", "drive-b-external", "monitor-colour", "midi", "auto-folder"], catalogMachine: "ste", filingSystem: "fat12", targetHardware: "floppy", driverBuild: "none", page: "0", emulator: "hatari", debugger: "hatari-debug" },
  { name: "Mega STE · TOS 2.06 with a hard-disk driver", machine: "megaste", addons: ["tos-206", "ram-4m", "hd-floppy", "scsi-internal", "driver-hddriver", "monitor-mono", "midi", "desktop-inf"], catalogMachine: "megaste", filingSystem: "fat16", targetHardware: "hd", driverBuild: "hddriver", page: "0", emulator: "hatari", debugger: "hatari-debug" },
  { name: "TT030 · TT RAM and internal SCSI", machine: "tt030", addons: ["tos-306", "ram-2m", "tt-ram", "hd-floppy", "scsi-internal", "driver-hddriver", "fpu-68882", "monitor-vga", "desktop-inf"], catalogMachine: "tt030", filingSystem: "fat16", targetHardware: "hd", driverBuild: "hddriver", page: "0", emulator: "hatari", debugger: "hatari-debug" },
  { name: "Falcon030 · internal IDE and VGA", machine: "falcon030", addons: ["tos-4xx", "ram-14m", "hd-floppy", "ide-internal", "driver-hddriver", "fpu-68882", "monitor-vga", "midi", "desktop-inf"], catalogMachine: "falcon030", filingSystem: "fat16", targetHardware: "hd", driverBuild: "hddriver", page: "0", emulator: "hatari", debugger: "hatari-debug" },
  { name: "ST with a Gotek", machine: "st", addons: ["tos-104", "ram-1m", "gotek", "drive-a-ds", "monitor-colour", "auto-folder"], catalogMachine: "st", filingSystem: "fat12", targetHardware: "floppy", driverBuild: "none", page: "0", emulator: "hatari", debugger: "hatari-debug" },
  { name: "ST with EmuTOS and ACSI2STM", machine: "st", addons: ["tos-emutos", "ram-4m", "drive-a-ds", "acsi2stm", "driver-emutos-builtin", "monitor-colour", "gemdos-hd-folder"], catalogMachine: "st", filingSystem: "fat16", targetHardware: "hd", driverBuild: "none", page: "0", emulator: "hatari", debugger: "hatari-debug" },
  { name: "STE with a 68030 accelerator", machine: "ste", addons: ["tos-206", "ram-4m", "drive-a-ds", "ide-adapter", "cf-adapter", "driver-hddriver", "acc-68030-pak", "fpu-68881", "monitor-vga", "desktop-inf"], catalogMachine: "ste", filingSystem: "fat16", targetHardware: "hd", driverBuild: "hddriver", page: "0", emulator: "hatari", debugger: "hatari-debug" },
  { name: "Mega ST · UltraSatan and the ICD driver", machine: "megast", addons: ["tos-102", "ram-2m", "drive-a-ds", "ultrasatan", "driver-icd", "blitter", "monitor-mono", "cartridge-port", "auto-folder"], catalogMachine: "megast", filingSystem: "fat16", targetHardware: "hd", driverBuild: "icd", page: "0", emulator: "hatari", debugger: "hatari-debug" },
];

//: A GEMDOS volume is FAT12 on a floppy and FAT16 on a hard drive, and a
//: partitioned drive carries a table as well. There is nothing else to
//: choose between.
const WORKBENCH_FILE_SYSTEMS = [
  ["fat12", "FAT12 · floppy"],
  ["fat16", "FAT16 · hard-drive partition"],
  ["fat16-ahdi", "FAT16 on a drive with an AHDI table"],
  ["fat16-mbr", "FAT16 on a drive with an MBR table"],
];
//: The memory a TOS machine can hold, from a 520ST through to a fully
//: populated Falcon.
const WORKBENCH_MEMORY = [
  ["512K", "512 KiB"], ["1M", "1 MiB"], ["2M", "2 MiB"],
  ["2.5M", "2.5 MiB"], ["4M", "4 MiB"], ["14M", "14 MiB"],
];
//: Which driver a prepared drive is expected to boot through, so a profile
//: can say what the finished drive should carry.
const DRIVE_DRIVER_BUILDS = [
  ["none", "Not used · floppy only"],
  ["emutos", "None · EmuTOS reads the drive itself"],
  ["ahdi", "Atari AHDI"],
  ["hddriver", "HDDRIVER"],
  ["pp", "PP driver"],
  ["icd", "ICD Pro driver"],
];
const WORKBENCH_EMULATORS = [["auto", "Automatic for machine"], ["hatari", "Hatari. Every ST, STE, TT and Falcon, floppy, hard drive and folder"]];
const WORKBENCH_DEBUGGERS = [["auto", "Automatic for emulator"], ["hatari-debug", "Hatari debugger"]];
let cachedHardwareCatalogue = null;

async function hardwareProfileCatalogue() {
  if (!cachedHardwareCatalogue) cachedHardwareCatalogue = await api("/api/hardware-profiles");
  return cachedHardwareCatalogue;
}

function hardwareAddonMarkup(catalogue, machine, selected = []) {
  const chosen = new Set(selected);
  const relevant = catalogue.addons.filter(addon => addon.machines.includes(machine));
  return Object.entries(catalogue.groups).map(([group, definition]) => {
    const addons = relevant.filter(addon => addon.group === group);
    if (!addons.length) return "";
    if (Number(definition.max) === 1) {
      const current = addons.find(addon => chosen.has(addon.id));
      return `<div class="hardware-addon-select field" data-addon-group="${esc(group)}"><label for="profile-addon-${esc(group)}">${esc(definition.label)}</label><select id="profile-addon-${esc(group)}" name="profileAddonSelect"><option value="">None</option>${addons.map(addon => `<option value="${esc(addon.id)}" ${chosen.has(addon.id) ? "selected" : ""}>${esc(addon.label)}</option>`).join("")}</select><small data-addon-description>${current ? `${esc(current.description)} · ${current.emulator === "profile" ? "Validation only" : `Driven by ${esc(current.emulator)}`}` : "No additional hardware selected."}</small></div>`;
    }
    return `<fieldset class="hardware-addon-group" data-addon-group="${esc(group)}" data-addon-max="${Number(definition.max)}"><legend>${esc(definition.label)} · select up to ${Number(definition.max)}</legend><div class="hardware-addon-options">${addons.map(addon => `<label class="hardware-addon"><input type="checkbox" name="profileAddon" value="${esc(addon.id)}" data-addon-group="${esc(group)}" ${chosen.has(addon.id) ? "checked" : ""}><span><b>${esc(addon.label)}</b><small>${esc(addon.description)}</small><em>${addon.emulator === "profile" ? "Validation only" : `Driven by ${esc(addon.emulator)}`}</em></span></label>`).join("")}</div></fieldset>`;
  }).join("");
}

function editorTargetProfile(pane) {
  const active = activeWorkbenchProfile().profile || {};
  const applied = pane?.image?.hardwareProfile || {};
  return {
    ...active,
    ...applied,
    targetHardware: pane?.image?.targetHardware || applied.targetHardware || active.targetHardware || "auto",
  };
}

function storedCollection(key, fallback = []) {
  try {
    const value = JSON.parse(persistentStorage.getItem(key) || "null");
    return Array.isArray(value) ? value : fallback;
  } catch (_error) { return fallback; }
}

function saveCollection(key, value) {
  persistentStorage.setItem(key, JSON.stringify(value));
}

function storedHardwareProfiles() {
  const saved = storedCollection(PROFILE_STORAGE_KEY, []);
  const schemaKey = `${PROFILE_STORAGE_KEY}-schema`;
  if (persistentStorage.getItem(schemaKey) === "6" && saved.length) return saved;
  // Profile names shipped by earlier releases, replaced by the machine list
  // the hardware catalogue now supplies.
  const superseded = new Set(saved.filter(profile => !ONLINE_MACHINES.some(([value]) => value === profile.machine)).map(profile => profile.name));
  const builtInNames = new Set(BUILTIN_PROFILES.map(profile => profile.name));
  const migrated = [
    ...BUILTIN_PROFILES.map(profile => ({ ...profile, addons: [...(profile.addons || [])] })),
    ...saved.filter(profile => !builtInNames.has(profile.name) && !superseded.has(profile.name)),
  ];
  saveCollection(PROFILE_STORAGE_KEY, migrated);
  persistentStorage.setItem(schemaKey, "6");
  return migrated;
}

function downloadDocument(name, content, type = "application/json") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function analysisLoading(title, detail) {
  showModal(
    `<div class="analysis-loading"><span class="modal-progress-icon">↻</span><h2>${esc(title)}</h2><p>${esc(detail)}</p><span class="progress"><i></i></span></div>`,
    null,
    { replace: modal.open }
  );
}

function replaceAnalysisLoading(html, onSubmit = null) {
  if (!modal.open) return false;
  showModal(html, onSubmit, { replace: true });
  return true;
}

async function runHealthCheck(index) {
  const pane = panes[index];
  modal.classList.add("busy");
  setModalProgress({
    title: "Checking image health",
    message: `Starting the structural scan of ${pane.image.name}…`,
    details: [
      { label: "Large images", value: "Directory traversal can take several minutes" },
      { label: "Safety", value: "This check is read-only and may be aborted at a safe boundary" },
    ],
  });
  try {
    return await trackedPaneOperation(
      index,
      "Checking image health",
      operationId => api(
        `/api/images/${pane.image.id}/health?${new URLSearchParams({ operationId })}`
      ),
      { abortMode: "read-only" },
    );
  } finally {
    modal.classList.remove("busy");
  }
}

function renderHealthDashboard(index, report) {
  const pane = panes[index];
  const icon = { pass: "✓", warn: "!", fail: "×" };
  const renderFinding = finding => (
    typeof finding === "string"
      ? `<li>${esc(finding)}</li>`
      : `<li><strong>${esc(finding.title || finding.name || "Finding")}</strong>${finding.detail ? `<small>${esc(finding.detail)}</small>` : ""}</li>`
  );
  const renderCheck = check => `<article class="health-check ${esc(check.status)}"><b>${icon[check.status] || "·"}</b><span><strong>${esc(check.name)}</strong><small>${esc(check.detail)}</small>${check.findings?.length ? `<details class="health-findings" ${check.status === "fail" ? "open" : ""}><summary>${check.findings.length} itemised ${check.findings.length === 1 ? "failure" : "failures"}</summary><ol>${check.findings.map(renderFinding).join("")}</ol></details>` : ""}</span></article>`;
  if (!replaceAnalysisLoading(`<div class="analysis-dialog wide-analysis">
      <header><div><small>UNIFIED IMAGE HEALTH</small><h2>${esc(pane.image.name)}</h2></div><span class="health-score ${esc(report.status)}">${esc(report.status)}</span></header>
      <div class="health-checks">${report.checks.map(renderCheck).join("") || "<p>No checks were applicable.</p>"}</div>
      ${report.repairable.length ? `<div class="help-note"><strong>Safe repairs available</strong>${report.repairable.map(item => `<p>${esc(item.label)} · ${esc(item.detail)}</p>`).join("")}</div>` : ""}
      <div class="modal-actions"><button class="button ghost" value="cancel">Close</button>${report.repairable.map(item => `<button class="button" data-health-repair="${esc(item.action)}" data-health-root="${esc(item.root || "")}" type="button">${esc(item.label)}</button>`).join("")}<button class="button primary" data-refresh-health type="button">Run again</button></div>
    </div>`)) return false;
  modalContent.querySelector("[data-refresh-health]").onclick = async event => {
    event.currentTarget.disabled = true;
    try {
      renderHealthDashboard(index, await runHealthCheck(index));
    } catch (error) {
      toast(error.message, true);
    }
  };
  modalContent.querySelectorAll("[data-health-repair]").forEach(button => button.onclick = async () => {
    try {
      button.disabled = true;
      const data = await api(`/api/images/${pane.image.id}/health/repair`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: button.dataset.healthRepair, root: button.dataset.healthRoot || undefined }) });
      pane.image = data.image;
      await refreshCurrentView(index);
      renderHealthDashboard(index, await runHealthCheck(index));
    } catch (error) {
      button.disabled = false;
      toast(error.message, true);
    }
  });
  return true;
}

function showHealthDashboard(index) {
  const pane = panes[index];
  const large = pane.image.size >= 20 * 1024 * 1024 || ["hd", "gemdos"].includes(pane.image.kind);
  showModal(`<div class="analysis-dialog health-introduction">
    <small>READ-ONLY IMAGE AUDIT</small>
    <h2>Check ${esc(pane.image.name)}</h2>
    <div class="help-warning"><strong>${large ? "This may take several minutes." : "This may take a little while."}</strong> Atari File Forge will traverse the filesystem, validate its structure and check the target profile. Very large hard-drive images may not produce a result immediately.</div>
    <div class="help-note"><strong>It has not hung:</strong> the progress view will show the current directory. You may use Abort operation to stop at the next safe boundary. No image data is changed by the health check.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="run">Run health check</button></div>
  </div>`, async () => {
    const report = await runHealthCheck(index);
    renderHealthDashboard(index, report);
    return false;
  });
}

//: Checking the software already installed on a drive: whether every program
//: on it is a program the machine would actually run, and whether the desktop
//: still names files that are there. Only the second has a repair, because it
//: is the only one whose right answer can be proved from the drive alone.
const DRIVE_SOFTWARE_AUDIT_AVAILABLE = true;

//: One folder's finding, with its repair offered only when there is one.
function driveSoftwareFindingMarkup(finding) {
  const repairs = finding.repairs || [];
  const warnings = finding.warnings || [];
  return `
    <div class="staged-title" data-finding="${esc(finding.path)}">
      <div>
        <b>${esc(drivePath("", finding.path))}</b>
        <small>${finding.fileCount} file${finding.fileCount === 1 ? "" : "s"}${finding.programs?.length ? ` · ${esc(finding.programs.join(", "))}` : ""}</small>
        ${repairs.map(repair => `<small class="staged-conflict">${esc(repair)}</small>`).join("")}
        ${warnings.map(warning => `<small class="staged-conflict">${esc(warning)}</small>`).join("")}
        ${repairs.length || warnings.length ? "" : '<small class="muted">Nothing to report.</small>'}
      </div>
      <div class="staged-actions">
        ${repairs.length
          ? `<label class="check-field"><input type="checkbox" name="repair" value="${esc(finding.path)}" checked> Repair</label>`
          : ""}
      </div>
    </div>`;
}

function showDriveSoftwareAudit(index) {
  const pane = panes[index];
  //: The first pass reads and the repair writes, so a read-only volume on a
  //: hard drive is still worth checking; the repair is what would be refused.
  const auditable = paneAcceptsInstall(pane)
    || (pane?.image?.kind === "gemdos" && Boolean(pane.image.hardDisk));
  if (!auditable) {
    toast("Installed software auditing is available only for a volume on a hard drive.", true);
    return;
  }
  const driveLetter = pane.partitionName || pane.image.driveLetter || "";
  const current = pane.path;
  showModal(`<div class="analysis-dialog health-introduction">
    <small>INSTALLED DRIVE SOFTWARE</small>
    <h2>Check installed drive software</h2>
    <div class="help-warning"><strong>This can take several minutes on a large drive image.</strong> Atari File Forge walks every folder that holds a program, reads each program's header and compares what the desktop installs with what is actually on the volume. Progress remains visible and the scan can be aborted safely.</div>
    <div class="field"><label>Scan</label><select name="root"><option value="">Whole volume (${esc(drivePath(driveLetter, ""))})</option>${current ? `<option value="${esc(current)}">Current folder (${esc(drivePath(driveLetter, current))})</option>` : ""}</select></div>
    <div class="help-note">The first pass is read-only. A desktop record naming a file that is not on the volume is the one provable fault, so it is the only one offered as a repair; a program whose header does not parse is reported and never rewritten.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Close</button><button class="button primary" type="submit">Run check</button></div>
  </div>`, async form => {
    const root = String(form.get("root") || "");
    const partition = pane.partition == null ? "" : `&partition=${pane.partition}`;
    const report = await trackedPaneOperation(index, "Checking installed drive software…", operationId =>
      api(`/api/images/${pane.image.id}/drive-software/audit?root=${encodeURIComponent(root)}&operationId=${encodeURIComponent(operationId)}${partition}`));
    renderDriveSoftwareAudit(index, report);
    return false;
  });
}

function renderDriveSoftwareAudit(index, report) {
  const pane = panes[index];
  const findings = report.directories || [];
  showModal(`<div class="analysis-dialog">
    <small>INSTALLED DRIVE SOFTWARE</small>
    <h2>${report.checked} folder${report.checked === 1 ? "" : "s"} checked</h2>
    <p>${report.repairable} with a provable repair · ${report.warnings} with something worth reading · scanned from ${esc(drivePath(pane.partitionName || "", report.root || ""))}</p>
    <div class="staged-title-list">${findings.map(driveSoftwareFindingMarkup).join("") || '<p class="muted">No folder on this volume holds a program.</p>'}</div>
    <div class="help-note">Repairing removes the desktop records listed above and nothing else. The check is run again before anything is written, so a result that has gone stale is refused rather than acted on.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Close</button><button class="button primary" type="submit" ${report.repairable ? "" : "disabled"}>Repair the folders ticked</button></div>
  </div>`, async form => {
    const directories = form.getAll("repair").map(String);
    if (!directories.length) return toast("Tick at least one folder to repair.", true) || false;
    const result = await trackedPaneOperation(index, "Repairing installed drive software…", operationId =>
      api(`/api/images/${pane.image.id}/drive-software/repair`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ directories, partition: pane.partition, operationId }),
      }));
    pane.image = result.image;
    await loadDirectory(index);
    toast(`${result.repair.count} folder${result.repair.count === 1 ? "" : "s"} repaired.`);
  }, { replace: true });
}

async function showSelectionPreflight(index) {
  const pane = panes[index];
  const items = selectedEntries(index).map(entry => ({
    name: entry.name,
    source: entryImagePath(pane, entry),
    type: entry.type,
    attributes: entry.attributes || entry.attr || "",
    datestamp: entry.datestamp || "",
    filetype: entry.filetype || "",
  }));
  if (!items.length) return toast("Select one or more items to dry-run.", true);
  analysisLoading("Dry-run preflight", `Reviewing ${items.length} selected item${items.length === 1 ? "" : "s"}…`);
  try {
    const report = await api(`/api/images/${pane.image.id}/preflight`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation: "selection", changes: items })
    });
    const markup = compatibilityReportMarkup(report, {
      heading: report.summary,
      continueLabel: "Close",
    }).replace(
      /<button class="button ghost" value="cancel">Cancel<\/button><button class="button primary" name="action" value="continue"[^>]*>Close<\/button>/,
      `<button class="button" type="button" data-accept-preflight ${report.canProceed ? "" : "disabled"}>Keep with saved image</button><button class="button primary" value="cancel">Close</button>`,
    );
    if (!replaceAnalysisLoading(markup)) return;
    wireCompatibilityExports(report, pane.image.name);
    modalContent.querySelector("[data-accept-preflight]").onclick = async event => {
      event.currentTarget.disabled = true;
      try {
        const accepted = await api(`/api/images/${pane.image.id}/preflight/accept`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(report),
        });
        toast(`Compatibility report retained for the next saved package · ${accepted.acceptedAt}`);
      } catch (error) {
        event.currentTarget.disabled = false;
        toast(error.message, true);
      }
    };
  } catch (error) { toast(error.message, true); modal.close(); }
}

async function showDeploymentAssistant(index) {
  const pane = panes[index];
  let targets;
  try {
    targets = (await api(`/api/images/${pane.image.id}/deployment/targets`)).targets;
  } catch (error) {
    return toast(error.message, true);
  }
  const available = targets.filter(target => target.available);
  showModal(`<div class="deployment-assistant">
    <header class="modal-heading"><span class="modal-kicker">HARDWARE DEPLOYMENT</span><h2>Build media for ${esc(pane.image.name)}</h2><p>Atari File Forge works from an isolated snapshot, validates the exact target tree and leaves the open image unchanged.</p></header>
    <div class="deployment-layout">
      <section class="deployment-settings">
        <label>Target<select name="deploymentTarget">${targets.map(target => `<option value="${esc(target.id)}" ${target.available ? "" : "disabled"}>${esc(target.label)}${target.available ? "" : " · unavailable"}</option>`).join("")}</select></label>
        <div class="deployment-target-help" aria-live="polite"></div>
        <fieldset class="deployment-gotek-options"><legend>FlashFloppy navigation</legend><label>Mode<select name="gotekMode"><option value="native">Native filenames and folders</option><option value="indexed">Indexed DSKA0000 layout</option></select></label><label>First index<input name="startIndex" type="number" min="0" max="9999" value="0"></label></fieldset>
        <div class="help-warning"><strong>Back up the working card or USB device first.</strong> The ZIP is a reviewed directory tree, not permission to overwrite a known-good deployment.</div>
      </section>
      <section class="deployment-review" aria-live="polite"><div class="empty-list">Choose a target, then validate the deployment.</div></section>
    </div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Close</button><button class="button" type="button" data-plan-deployment ${available.length ? "" : "disabled"}>Validate layout</button><button class="button primary" type="button" data-download-deployment disabled>Download deployment ZIP</button></div>
  </div>`);
  if (!available.length) {
    modalContent.querySelector(".deployment-review").innerHTML = '<div class="help-warning">This image type has no supported deployment layout.</div>';
    return;
  }
  const targetSelect = modalContent.querySelector('[name="deploymentTarget"]');
  targetSelect.value = available[0].id;
  const gotekOptions = modalContent.querySelector(".deployment-gotek-options");
  const targetHelp = modalContent.querySelector(".deployment-target-help");
  const review = modalContent.querySelector(".deployment-review");
  const buildButton = modalContent.querySelector("[data-download-deployment]");
  let plan = null;
  const payload = () => ({
    target: targetSelect.value,
    gotekMode: modalContent.querySelector('[name="gotekMode"]').value,
    startIndex: Number(modalContent.querySelector('[name="startIndex"]').value || 0),
  });
  const targetChanged = () => {
    const target = targets.find(item => item.id === targetSelect.value);
    targetHelp.innerHTML = `<strong>${esc(target?.label || "")}</strong><span>${esc(target?.description || target?.reason || "")}</span>`;
    gotekOptions.hidden = targetSelect.value !== "gotek";
    plan = null;
    buildButton.disabled = true;
    review.innerHTML = '<div class="empty-list">Validate again after changing the target layout.</div>';
  };
  targetSelect.onchange = targetChanged;
  modalContent.querySelectorAll('[name="gotekMode"], [name="startIndex"]').forEach(control => control.onchange = targetChanged);
  targetChanged();
  modalContent.querySelector("[data-plan-deployment]").onclick = async event => {
    event.currentTarget.disabled = true;
    review.innerHTML = "<p>Finalising and hashing an isolated snapshot…</p>";
    try {
      plan = await trackedPaneOperation(index, "Validating hardware deployment", operationId => api(`/api/images/${pane.image.id}/deployment/plan`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload(), operationId }),
      }), { abortMode: "read-only" });
      review.innerHTML = `<header><strong>${esc(plan.targetLabel)}</strong><span>${plan.entries.length} file${plan.entries.length === 1 ? "" : "s"} · ${humanSize(plan.entries.reduce((total, entry) => total + entry.size, 0))}</span></header>
        <div class="deployment-file-list">${plan.entries.map(entry => `<article><span><b>${esc(entry.path)}</b><small>${esc(entry.role)} · ${humanSize(entry.size)}</small></span><code title="SHA-256 ${esc(entry.sha256)}">${esc(entry.sha256.slice(0, 16))}…</code></article>`).join("")}</div>
        <div class="finding-list">${plan.issues.map(item => `<p class="finding ${esc(item.severity)}"><b>${esc(item.severity)}</b>${esc(item.message)}</p>`).join("") || '<p class="finding pass"><b>ready</b>The generated layout passed its automated checks.</p>'}</div>
        <details open><summary>Installation and verification</summary><ol>${plan.instructions.map(step => `<li>${esc(step)}</li>`).join("")}</ol></details>`;
      buildButton.disabled = !plan.canProceed;
    } catch (error) {
      plan = null;
      buildButton.disabled = true;
      review.innerHTML = `<div class="help-warning">${esc(error.message)}</div>`;
    } finally {
      event.currentTarget.disabled = false;
    }
  };
  buildButton.onclick = async () => {
    if (!plan) return;
    buildButton.disabled = true;
    try {
      const result = await trackedPaneOperation(index, "Building hardware deployment ZIP", async operationId => {
        const response = await fetch(`/api/images/${pane.image.id}/deployment/package`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...payload(), expectedRevision: plan.source.revision, operationId }),
        });
        return downloadResponse(response, `${pathNameWithoutExtension(pane.image.name)}-${plan.target}-deployment.zip`);
      }, { abortMode: "read-only" });
      toast(`${result.filename} downloaded · ${humanSize(result.size)}`);
    } catch (error) {
      toast(error.message, true);
    } finally {
      buildButton.disabled = !plan?.canProceed;
    }
  };
}

function selectedInspectable(index) {
  const pane = panes[index];
  const entry = selectedEntry(index);
  return entry && entry.type !== "dir" && entry.type !== "directory"
    ? { pane, entry, path: entryImagePath(pane, entry) }
    : null;
}

async function showFileInspector(index) {
  const selected = selectedInspectable(index);
  if (!selected) return toast("Select one file to inspect.", true);
  return openFileEditor(index, selected.entry.name, null, selected.path);
}

function fileContextQuery(pane, path, extra = {}) {
  return new URLSearchParams({
    path,
    ...(pane.partition != null ? { partition: pane.partition } : {}),
    ...(pane.side != null ? { side: pane.side } : {}),
    ...extra,
  });
}

async function openFileHexEditor(index, entry, path, host = null, initialOffset = 0, target = null) {
  const pane = panes[index];
  if (!window.AtariHexEditor) return toast("The hex editor could not be opened.", true);
  await window.AtariHexEditor.open({
    host: host || document.querySelector(`.pane[data-pane="${index}"]`),
    image: { id: pane.image.id, name: entry.name, size: Number(entry.length || 0), readOnly: Boolean(target?.readOnly || pane.image.readOnly) },
    request: api,
    notify: toast,
    endpoint: target?.hexEndpoint || `/api/images/${pane.image.id}/file-hex`,
    context: target?.context || { path, ...(pane.partition != null ? { partition: pane.partition } : {}), ...(pane.side != null ? { side: pane.side } : {}) },
    scope: "file",
    kicker: target ? "READ-ONLY ARCHIVE MEMBER BYTES" : null,
    title: entry.name,
    initialOffset,
    exportUrl: target?.exportUrl || fileExportUrl(pane, path),
    onSaved: updatedImage => {
      pane.image = updatedImage;
      rememberOpenPanes();
    },
  });
  if (!target) await refreshCurrentView(index);
}

function fileDownloadUrl(pane, path) {
  const query = fileContextQuery(pane, path, { bundle: "metadata" });
  return `/api/images/${pane.image.id}/file?${query}`;
}

function fileExportUrl(pane, path) {
  return `/api/images/${pane.image.id}/file?${fileContextQuery(pane, path)}`;
}

function disassemblyComment(row) {
  return [
    row.comment || "",
    row.references?.length ? `referenced from ${row.references.map(value => `&${Number(value).toString(16).toUpperCase()}`).join(", ")}` : "",
  ].filter(Boolean).join("; ");
}

function disassemblyText(report) {
  return report.rows.map(row => {
    const address = Number(row.address).toString(16).toUpperCase().padStart(4, "0");
    const instruction = `${row.mnemonic}${row.operand ? ` ${row.operand}` : ""}`;
    const comment = disassemblyComment(row);
    return `${row.label ? `${row.label}:\n` : ""}${`&${address}`.padEnd(9)}${String(row.bytes || "").padEnd(14)}${instruction.padEnd(25)}${comment ? `; ${comment}` : ""}`.trimEnd();
  }).join("\n");
}

function disassemblyAssemblySource(report) {
  return report.rows.map(row => {
    const instruction = `${row.mnemonic}${row.operand ? ` ${row.operand}` : ""}`;
    const comment = disassemblyComment(row);
    return `${row.label ? `${row.label}:\n` : ""}    ${instruction}${comment ? ` ; ${comment}` : ""}`;
  }).join("\n");
}

function assemblySourceEditor(entry, report) {
  return new Promise(resolve => {
    const shade = document.createElement("div");
    shade.className = "editor-choice-shade";
    shade.setAttribute("role", "dialog");
    shade.setAttribute("aria-modal", "true");
    shade.innerHTML = `<form class="editor-choice-card editor-assembly-card"><header><div><small>EXTERNAL ASSEMBLER WORKFLOW</small><h2>Reassemble ${esc(entry.name)}</h2></div></header><div class="help-warning"><strong>Dangerous operation:</strong> a successful build replaces the whole binary. Labels and comments are generated starting points, so review assembler syntax, origin and emitted length before continuing.</div><div class="field-grid two"><div class="field"><label>Architecture</label><input name="architecture" value="${esc(report.architecture)}" readonly></div><div class="field"><label>Origin</label><input name="origin" value="0x${Number(report.origin).toString(16).toUpperCase()}"></div></div><div class="field"><label>Assembly source</label><textarea name="source" rows="22" spellcheck="false">${esc(disassemblyAssemblySource(report))}</textarea></div><div class="modal-actions"><button type="button" class="button ghost" data-assembly-cancel>Cancel</button><button type="submit" class="button danger">Assemble and replace binary…</button></div></form>`;
    const finish = value => { shade.remove(); resolve(value); };
    shade.querySelector("[data-assembly-cancel]").onclick = () => finish(null);
    shade.querySelector("form").onsubmit = async event => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.currentTarget));
      if (!await confirmChoice("Replace the saved binary?", "The complete file is replaced with the assembler output.", { confirmLabel: "Assemble and replace", danger: true, note: "The current image checkpoint can undo it." })) return;
      finish(values);
    };
    shade.onkeydown = event => { if (event.key === "Escape") finish(null); else trapFocus(shade, event); };
    modal.append(shade);
    shade.querySelector("textarea").focus();
  });
}

function disassemblySource(report) {
  return report.rows.map(row => {
    const address = Number(row.address).toString(16).toUpperCase().padStart(4, "0");
    const comments = disassemblyComment(row);
    const instruction = `${row.mnemonic}${row.operand ? ` ${row.operand}` : ""}`;
    return `${row.label ? `<div class="disassembly-label"><span class="disassembly-fold-cell"></span><span>${esc(row.label)}:</span></div>` : ""}<div class="disassembly-source-line${row.reachable === false ? " unreachable" : ""}" data-offset="${Number(row.offset)}" data-address="${Number(row.address)}" tabindex="0" title="Double-click to open these bytes in Hex">
      <span class="disassembly-fold-cell" aria-hidden="true"></span><span class="disassembly-address">&amp;${address}</span><span class="disassembly-bytes" title="${esc(row.bytes)}">${esc(row.bytes)}</span><span class="disassembly-instruction" title="${esc(instruction)}">${esc(instruction)}</span><span class="disassembly-comment" ${comments ? `title="${esc(comments)}"` : ""}>${comments ? `; ${esc(comments)}` : ""}</span>
    </div>`;
  }).join("");
}

function disassemblyColumnStyle(report) {
  const rows = Array.isArray(report?.rows) ? report.rows : [];
  const characterLength = value => Array.from(String(value || "")).length;
  const widestBytes = rows.reduce((width, row) => Math.max(width, characterLength(row.bytes)), "Bytes".length);
  const widestInstruction = rows.reduce((width, row) => {
    const instruction = `${row.mnemonic || ""}${row.operand ? ` ${row.operand}` : ""}`;
    return Math.max(width, characterLength(instruction));
  }, "Instruction".length);
  // Three spare monospace cells keep the next column visually separate. Very
  // long data declarations remain available through their tooltip instead of
  // pushing useful annotations beyond the editor window.
  const bytesWidth = Math.max(8, Math.min(30, widestBytes + 3));
  const instructionWidth = Math.max(14, Math.min(44, widestInstruction + 3));
  return `--disassembly-bytes-width:${bytesWidth}ch;--disassembly-instruction-width:${instructionWidth}ch`;
}

function editorMenus({ downloadUrl, downloadLabel = "Download with metadata…", canEdit = false, canSaveAs = canEdit, canChangeProperties = false, basic = false, readOnly = false } = {}) {
  const shortcut = value => `<kbd>${value}</kbd>`;
  return `<nav class="editor-menubar" aria-label="Editor menus">
    <details class="editor-menu"><summary>File</summary><div class="editor-menu-panel">
      <button type="button" data-editor-action="save" ${canEdit ? "disabled" : "disabled"}><span>Save</span>${shortcut("Ctrl+S")}</button>
      <button type="button" data-editor-action="save-as" ${canSaveAs ? "" : "disabled"}><span>Save As…</span>${shortcut("Ctrl+Shift+S")}</button>
      <button type="button" data-editor-action="export"><span>Export as text…</span></button>
      ${downloadUrl ? `<a href="${esc(downloadUrl)}"><span>${esc(downloadLabel)}</span></a>` : ""}
      <button type="button" data-editor-action="properties" ${canChangeProperties ? "" : "disabled"}><span>Properties…</span></button>
      <span class="editor-menu-separator" role="separator"></span>
      <button type="button" data-editor-action="close"><span>Close</span>${shortcut("Ctrl+W")}</button>
    </div></details>
    <details class="editor-menu"><summary>Edit</summary><div class="editor-menu-panel">
      <button type="button" data-editor-action="undo" ${canEdit ? "" : "disabled"}><span>Undo</span>${shortcut("Ctrl+Z")}</button>
      <button type="button" data-editor-action="redo" ${canEdit ? "" : "disabled"}><span>Redo</span>${shortcut("Ctrl+Y")}</button>
      <span class="editor-menu-separator" role="separator"></span>
      <button type="button" data-editor-action="cut" ${canEdit ? "" : "disabled"}><span>Cut</span>${shortcut("Ctrl+X")}</button>
      <button type="button" data-editor-action="copy"><span>Copy</span>${shortcut("Ctrl+C")}</button>
      <button type="button" data-editor-action="paste" ${canEdit ? "" : "disabled"}><span>Paste</span>${shortcut("Ctrl+V")}</button>
      <button type="button" data-editor-action="select-all"><span>Select All</span>${shortcut("Ctrl+A")}</button>
      <span class="editor-menu-separator" role="separator"></span>
      <button type="button" data-editor-action="find"><span>Find…</span>${shortcut("Ctrl+F")}</button>
      <button type="button" data-editor-action="find-replace" ${canEdit ? "" : "disabled"}><span>Find and Replace…</span>${shortcut("Ctrl+H")}</button>
      <button type="button" data-editor-action="search-image"><span>Search files in this image…</span></button>
      <button type="button" data-editor-action="find-references"><span>Find all references</span></button>
      <button type="button" data-editor-action="rename-symbol" ${canEdit ? "" : "disabled"}><span>Rename symbol…</span></button>
      <button type="button" data-editor-action="go-to-line"><span>Go to line…</span>${shortcut("Ctrl+G")}</button>
      <button type="button" data-editor-action="complete"><span>Complete at cursor…</span>${shortcut("Ctrl+Space")}</button>
      ${basic ? `<button type="button" data-editor-action="toggle-comment" ${canEdit ? "" : "disabled"}><span>Toggle comment</span>${shortcut("Ctrl+/")}</button>` : ""}
      <span class="editor-menu-separator" role="separator"></span>
      <button type="button" data-editor-action="line-duplicate" ${canEdit && !basic ? "" : "disabled"}><span>Duplicate line(s)</span></button>
      <button type="button" data-editor-action="line-up" ${canEdit && !basic ? "" : "disabled"}><span>Move line(s) up</span></button>
      <button type="button" data-editor-action="line-down" ${canEdit && !basic ? "" : "disabled"}><span>Move line(s) down</span></button>
      <button type="button" data-editor-action="line-join" ${canEdit && !basic ? "" : "disabled"}><span>Join selected lines</span></button>
      <button type="button" data-editor-action="line-delete" ${canEdit ? "" : "disabled"}><span>Delete line(s)</span></button>
    </div></details>
    <details class="editor-menu"><summary>View</summary><div class="editor-menu-panel editor-view-panel">
      ${basic ? `<fieldset><legend>Structure guidance</legend><label>Guide spacing<select data-structure-guide-size><option value="2">2</option><option value="4" selected>4</option><option value="8">8</option></select></label><button type="button" data-editor-action="structure-guides"><span>Hide structure guides</span></button><small>Live presentation only. Source and saved bytes are unchanged.</small></fieldset><span class="editor-menu-separator" role="separator"></span>` : ""}
      <button type="button" data-editor-action="fold-toggle-all"><span>Collapse all blocks</span></button>
      <button type="button" data-editor-action="sync-bytes"><span>Show synchronized bytes</span></button>
    </div></details>
    <details class="editor-menu"><summary>Tools</summary><div class="editor-menu-panel editor-tools-panel">
      ${basic ? `<fieldset ${canEdit ? "" : "disabled"}><legend>Renumber BASIC</legend><label>Start<input name="renumberStart" type="number" min="0" max="32767" value="10"></label><label>Step<input name="renumberStep" type="number" min="1" max="32767" value="10"></label><button class="basic-renumber" type="button">Renumber</button></fieldset><span class="editor-menu-separator" role="separator"></span>` : ""}
      <button type="button" data-editor-action="normalise-commands" ${canEdit ? "" : "disabled"}><span>Normalise recognised commands</span></button>
      <button type="button" data-editor-action="format-code" ${canEdit ? "" : "disabled"}><span>Format selection or file…</span></button>
      ${basic ? `<button type="button" data-editor-action="verify-basic"><span>Verify BASIC round trip</span></button><button type="button" data-editor-action="program-outline"><span>Program outline and call graph</span></button>` : ""}
      <button type="button" data-editor-action="dependencies"><span>Analyse file dependencies</span></button>
      ${basic ? '<button type="button" data-editor-action="cheat-candidates"><span>Find cheat candidates…</span></button>' : ""}
      <button type="button" data-editor-action="editor-history"><span>Editor history</span></button>
      <button type="button" data-editor-action="compare-saved"><span>Compare with saved file</span></button>
      <button type="button" data-editor-action="hex"><span>Open raw bytes in Hex</span></button>
      ${basic ? `<span class="editor-menu-separator" role="separator"></span><button type="button" data-editor-action="condense-code" ${canEdit ? "" : "disabled"}><span>Condense selection or program…</span></button><button type="button" data-editor-action="refactor-code" ${canEdit ? "" : "disabled"}><span>Refactor selection or program…</span></button>` : ""}
    </div></details>
    <details class="editor-menu"><summary>Project</summary><div class="editor-menu-panel">
      <button type="button" data-editor-action="project-bookmark"><span>Add bookmark at cursor…</span></button>
      <button type="button" data-editor-action="project-notes"><span>Project notes…</span></button>
      <button type="button" data-editor-action="project-manage"><span>Manage project metadata…</span></button>
      <button type="button" data-editor-action="run-emulator"><span>Run in configured emulator…</span></button>
      <button type="button" data-editor-action="debugger-workspace"><span>Emulator debugger workspace…</span></button>
      <button type="button" data-editor-action="project-tests"><span>Emulator and debugger results…</span></button>
    </div></details>
    <details class="editor-menu"><summary>Help</summary><div class="editor-menu-panel">
      <button type="button" data-editor-action="help-overview"><span>About this file and language</span></button>
      <button type="button" data-editor-action="help-reference"><span>Command reference…</span></button>
      <span class="editor-menu-separator" role="separator"></span>
      <button type="button" data-editor-action="help-problems"><span>Problems</span></button>
      <button type="button" data-editor-action="help-symbols"><span>Document symbols</span></button>
    </div></details>
    ${readOnly ? '<span class="editor-read-only">Read-only</span>' : ""}
  </nav>`;
}

function disassemblyMenus(downloadUrl, exportUrl, exportLabel = "Export original binary…") {
  const shortcut = value => `<kbd>${value}</kbd>`;
  return `<nav class="editor-menubar" aria-label="Disassembly editor menus">
    <details class="editor-menu"><summary>File</summary><div class="editor-menu-panel">
      <button type="button" data-disassembly-action="save-as"><span>Save As Disassembly…</span></button>
      <button type="button" data-disassembly-action="export"><span>Export disassembly as text…</span></button>
      ${exportUrl ? `<a href="${esc(exportUrl)}"><span>${esc(exportLabel)}</span></a>` : ""}
      ${downloadUrl ? `<a href="${esc(downloadUrl)}"><span>Download original with metadata…</span></a>` : ""}
      <span class="editor-menu-separator" role="separator"></span>
      <button type="button" data-disassembly-action="close"><span>Close</span>${shortcut("Ctrl+W")}</button>
    </div></details>
    <details class="editor-menu"><summary>Edit</summary><div class="editor-menu-panel">
      <button type="button" data-disassembly-action="copy"><span>Copy</span>${shortcut("Ctrl+C")}</button>
      <button type="button" data-disassembly-action="select-all"><span>Select All</span>${shortcut("Ctrl+A")}</button>
      <button type="button" data-disassembly-action="find"><span>Find…</span>${shortcut("Ctrl+F")}</button>
      <button type="button" data-disassembly-action="find-references"><span>Find references to selected address</span></button>
      <button type="button" data-disassembly-action="rename-symbol"><span>Rename selected symbol…</span></button>
    </div></details>
    <details class="editor-menu"><summary>View</summary><div class="editor-menu-panel">
      <button type="button" data-disassembly-action="fold-toggle-all"><span>Collapse all labelled blocks</span></button>
      <button type="button" data-disassembly-action="sync-bytes"><span>Show synchronized bytes</span></button>
    </div></details>
    <details class="editor-menu"><summary>Tools</summary><div class="editor-menu-panel">
      <button type="button" data-disassembly-action="inspect-data"><span>Inspect selected data…</span></button>
      <button type="button" data-disassembly-action="cheat-candidates"><span>Find cheat candidates…</span></button>
      <button type="button" data-disassembly-action="assemble"><span>Edit and reassemble…</span></button>
      <button type="button" data-disassembly-action="debug"><span>Emulator debugger workspace…</span></button>
      <button type="button" data-disassembly-action="hex"><span>Open raw bytes in Hex</span></button>
    </div></details>
    <details class="editor-menu"><summary>Project</summary><div class="editor-menu-panel">
      <button type="button" data-disassembly-action="mark-code"><span>Mark selection as code</span></button>
      <button type="button" data-disassembly-action="mark-text"><span>Mark selection as text</span></button>
      <button type="button" data-disassembly-action="mark-bytes"><span>Mark selection as bytes</span></button>
      <button type="button" data-disassembly-action="mark-words"><span>Mark selection as words</span></button>
      <button type="button" data-disassembly-action="mark-addresses"><span>Mark selection as addresses</span></button>
      <button type="button" data-disassembly-action="mark-bitmap"><span>Mark selection as bitmap</span></button>
      <span class="editor-menu-separator" role="separator"></span>
      <button type="button" data-disassembly-action="bookmark"><span>Bookmark selected address…</span></button>
      <button type="button" data-disassembly-action="comment"><span>Add or edit line comment…</span></button>
      <button type="button" data-disassembly-action="notes"><span>Project notes…</span></button>
      <button type="button" data-disassembly-action="symbols-import"><span>Import symbol file…</span></button>
      <button type="button" data-disassembly-action="symbols-export"><span>Export symbol file…</span></button>
      <button type="button" data-disassembly-action="outline"><span>Program outline and call graph</span></button>
      <button type="button" data-disassembly-action="history"><span>Project history</span></button>
      <button type="button" data-disassembly-action="run-emulator"><span>Run in configured emulator…</span></button>
      <button type="button" data-disassembly-action="tests"><span>Emulator and debugger results…</span></button>
    </div></details>
    <details class="editor-menu"><summary>Help</summary><div class="editor-menu-panel">
      <button type="button" data-disassembly-action="help-overview"><span>About this disassembly</span></button>
      <button type="button" data-disassembly-action="help-reference"><span>Instruction and library reference…</span></button>
      <button type="button" data-disassembly-action="help-symbols"><span>Discovered symbols…</span></button>
      <button type="button" data-disassembly-action="help-problems"><span>Disassembly cautions</span></button>
    </div></details>
    <span class="editor-read-only">Read-only disassembly</span>
  </nav>`;
}

function closeEditorMenus(root, except = null) {
  root.querySelectorAll(".editor-menu[open]").forEach(menu => {
    if (menu !== except) menu.removeAttribute("open");
  });
}

function installEditorMenuDismissal(root) {
  if (!root || root.dataset.menuDismissal === "1") return;
  root.dataset.menuDismissal = "1";
  const owner = root.ownerDocument;
  const dismissOutside = event => {
    if (!root.isConnected) {
      owner.removeEventListener("pointerdown", dismissOutside, true);
      return;
    }
    const activeMenu = event.target.closest?.(".editor-menu");
    if (!activeMenu || !root.contains(activeMenu)) closeEditorMenus(root);
  };
  const dismissSelection = event => {
    if (event.target.closest(".editor-menu-panel button, .editor-menu-panel a")) {
      queueMicrotask(() => closeEditorMenus(root));
    }
  };
  const dismissEscape = event => {
    if (event.key !== "Escape" || !root.querySelector(".editor-menu[open]")) return;
    event.preventDefault();
    event.stopPropagation();
    closeEditorMenus(root);
    root.querySelector(".editor-menu summary")?.focus();
  };
  const transferOpenMenu = menu => {
    if (!root.querySelector(".editor-menu[open]") || menu.open) return;
    closeEditorMenus(root, menu);
    menu.open = true;
  };
  root.querySelectorAll(".editor-menu").forEach(menu => {
    menu.addEventListener("pointerenter", () => transferOpenMenu(menu));
    menu.addEventListener("focusin", () => transferOpenMenu(menu));
  });
  owner.addEventListener("pointerdown", dismissOutside, true);
  root.addEventListener("click", dismissSelection);
  root.addEventListener("keydown", dismissEscape);
  modal.addEventListener("close", () => owner.removeEventListener("pointerdown", dismissOutside, true), { once: true });
}

// A deliberately tiny test seam for the permanent browser regression. It
// exposes behaviour, not application state or image data.
window.AtariEditorTestHooks = Object.freeze({ installEditorMenuDismissal });

let editorWindowController = null;

function installEditorWindow(root) {
  const previous = editorWindowController?.snapshot();
  editorWindowController?.destroy(true);
  const titleBar = root?.querySelector(":scope > header");
  if (!titleBar) return;
  const nativeClose = modal.querySelector(":scope > form > .modal-close");
  const controls = document.createElement("div");
  controls.className = "editor-window-controls";
  controls.innerHTML = `<button type="button" class="editor-window-maximise" title="Maximise editor" aria-label="Maximise editor"></button><button type="button" class="editor-window-close" title="Close editor" aria-label="Close editor">×</button>`;
  titleBar.classList.add("editor-window-titlebar");
  titleBar.append(controls);
  modal.classList.add("editor-window");

  const directions = ["n", "ne", "e", "se", "s", "sw", "w", "nw"];
  const handles = directions.map(direction => {
    const handle = document.createElement("span");
    handle.className = `editor-resize-handle editor-resize-${direction}`;
    handle.dataset.resizeDirection = direction;
    handle.tabIndex = 0;
    handle.setAttribute("role", "separator");
    handle.setAttribute("aria-label", `Resize editor from the ${direction.toUpperCase()} edge`);
    modal.append(handle);
    return handle;
  });
  const margin = 8;
  const minWidth = () => Math.min(520, Math.max(300, window.innerWidth - margin * 2));
  const minHeight = () => Math.min(340, Math.max(240, window.innerHeight - margin * 2));
  const currentRect = () => {
    const rect = modal.getBoundingClientRect();
    return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
  };
  const constrain = rectangle => {
    const width = Math.min(Math.max(rectangle.width, minWidth()), window.innerWidth - margin * 2);
    const height = Math.min(Math.max(rectangle.height, minHeight()), window.innerHeight - margin * 2);
    return {
      width,
      height,
      left: Math.min(Math.max(rectangle.left, margin), Math.max(margin, window.innerWidth - width - margin)),
      top: Math.min(Math.max(rectangle.top, margin), Math.max(margin, window.innerHeight - height - margin)),
    };
  };
  const setRect = rectangle => {
    const rect = constrain(rectangle);
    Object.assign(modal.style, {
      position: "fixed", margin: "0", maxWidth: "none", maxHeight: "none",
      left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px`,
    });
    return rect;
  };
  const preferredInitialRect = () => {
    // A desktop editor should feel like a working window, not a small prompt.
    // Scale down with the browser rather than relying on fixed dimensions that
    // either swamp a compact viewport or waste space on a large one.
    const width = Math.min(1080, Math.max(minWidth(), Math.round(window.innerWidth * .62)));
    const height = Math.min(760, Math.max(minHeight(), Math.round(window.innerHeight * .82)));
    return {
      width,
      height,
      left: Math.round((window.innerWidth - width) / 2),
      top: Math.round((window.innerHeight - height) / 2),
    };
  };
  const initial = previous?.rect || preferredInitialRect();
  let maximised = Boolean(previous?.maximised);
  let restoreRect = previous?.restoreRect || null;
  setRect(maximised ? { left: margin, top: margin, width: window.innerWidth - margin * 2, height: window.innerHeight - margin * 2 } : initial);
  const maximiseButton = controls.querySelector(".editor-window-maximise");
  const updateMaximiseButton = () => {
    maximiseButton.innerHTML = maximised
      ? '<svg viewBox="0 0 20 20" aria-hidden="true"><rect x="3" y="6" width="10" height="10" rx="1"/><path d="M7 6V3h10v10h-4"/></svg>'
      : '<svg viewBox="0 0 20 20" aria-hidden="true"><rect x="3" y="3" width="14" height="14" rx="1"/></svg>';
    maximiseButton.title = maximised ? "Restore editor" : "Maximise editor";
    maximiseButton.setAttribute("aria-label", maximiseButton.title);
    modal.classList.toggle("editor-window-maximised", maximised);
  };
  const toggleMaximise = () => {
    if (maximised) {
      maximised = false;
      setRect(restoreRect || initial);
    } else {
      restoreRect = currentRect();
      maximised = true;
      setRect({ left: margin, top: margin, width: window.innerWidth - margin * 2, height: window.innerHeight - margin * 2 });
    }
    updateMaximiseButton();
  };
  updateMaximiseButton();

  let pointerCleanup = null;
  const beginPointerOperation = (event, direction = "move") => {
    if (event.button !== 0) return;
    if (maximised) return;
    event.preventDefault();
    const origin = currentRect();
    const startX = event.clientX;
    const startY = event.clientY;
    const move = moveEvent => {
      const dx = moveEvent.clientX - startX;
      const dy = moveEvent.clientY - startY;
      if (direction === "move") return setRect({ ...origin, left: origin.left + dx, top: origin.top + dy });
      let { left, top, width, height } = origin;
      if (direction.includes("e")) width += dx;
      if (direction.includes("s")) height += dy;
      if (direction.includes("w")) { left += dx; width -= dx; }
      if (direction.includes("n")) { top += dy; height -= dy; }
      setRect({ left, top, width, height });
    };
    const end = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      document.removeEventListener("pointercancel", end);
      pointerCleanup = null;
    };
    pointerCleanup?.();
    pointerCleanup = end;
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", end, { once: true });
    document.addEventListener("pointercancel", end, { once: true });
  };
  const resizeByKeyboard = (direction, event) => {
    if (maximised || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
    event.preventDefault();
    const amount = event.shiftKey ? 30 : 10;
    const dx = event.key === "ArrowLeft" ? -amount : event.key === "ArrowRight" ? amount : 0;
    const dy = event.key === "ArrowUp" ? -amount : event.key === "ArrowDown" ? amount : 0;
    const origin = currentRect();
    let { left, top, width, height } = origin;
    if (direction.includes("e")) width += dx;
    if (direction.includes("s")) height += dy;
    if (direction.includes("w")) { left += dx; width -= dx; }
    if (direction.includes("n")) { top += dy; height -= dy; }
    setRect({ left, top, width, height });
  };
  const drag = event => {
    if (event.target.closest("button, a, input, select, textarea, summary")) return;
    beginPointerOperation(event);
  };
  const doubleClick = event => {
    if (!event.target.closest("button, a, input, select, textarea, summary")) toggleMaximise();
  };
  const viewportChanged = () => {
    if (maximised) setRect({ left: margin, top: margin, width: window.innerWidth - margin * 2, height: window.innerHeight - margin * 2 });
    else setRect(currentRect());
  };
  titleBar.addEventListener("pointerdown", drag);
  titleBar.addEventListener("dblclick", doubleClick);
  maximiseButton.addEventListener("click", toggleMaximise);
  controls.querySelector(".editor-window-close").addEventListener("click", () => nativeClose.click());
  handles.forEach(handle => {
    handle.addEventListener("pointerdown", event => beginPointerOperation(event, handle.dataset.resizeDirection));
    handle.addEventListener("keydown", event => resizeByKeyboard(handle.dataset.resizeDirection, event));
  });
  window.addEventListener("resize", viewportChanged);

  const destroy = (keepGeometry = false) => {
    pointerCleanup?.();
    titleBar.removeEventListener("pointerdown", drag);
    titleBar.removeEventListener("dblclick", doubleClick);
    window.removeEventListener("resize", viewportChanged);
    controls.remove();
    handles.forEach(handle => handle.remove());
    if (!keepGeometry) {
      modal.classList.remove("editor-window", "editor-window-maximised");
      ["position", "margin", "max-width", "max-height", "left", "top", "width", "height"].forEach(property => modal.style.removeProperty(property));
    }
    if (editorWindowController?.destroy === destroy) editorWindowController = null;
  };
  editorWindowController = {
    snapshot: () => ({ rect: currentRect(), maximised, restoreRect }),
    destroy,
  };
  modal.addEventListener("close", () => destroy(), { once: true });
}

function editorTextPosition(editor) {
  const before = editor.value.slice(0, editor.selectionStart);
  const lines = before.split("\n");
  return { line: lines.length, column: lines.at(-1).length + 1 };
}

function updateSourceEditorStatus(root) {
  const editor = root.querySelector(".source-content");
  if (!editor) return;
  const position = editorTextPosition(editor);
  const lines = editor.value.split("\n").length;
  const dirty = editor.value !== editor.dataset.savedValue;
  root.querySelector(".editor-document-state").textContent = editor.readOnly ? "Read-only" : dirty ? "Modified" : "Saved";
  root.querySelector(".editor-position").textContent = `Ln ${position.line}, Col ${position.column}`;
  root.querySelector(".editor-size").textContent = `${lines.toLocaleString()} line${lines === 1 ? "" : "s"} · ${editor.value.length.toLocaleString()} characters`;
  root.querySelector('[data-editor-action="save"]').disabled = editor.readOnly || !dirty;
}

function openEditorSearch(root, editor, replaceMode = false) {
  let panel = root.querySelector(".editor-search-panel");
  const initialSelection = { start: editor.selectionStart, end: editor.selectionEnd };
  if (!panel) {
    panel = document.createElement("section");
    panel.className = "editor-search-panel";
    panel.setAttribute("role", "search");
    panel.innerHTML = `<div class="editor-search-fields"><label>Find<input type="search" data-search-query autocomplete="off"></label><label class="editor-replace-field">Replace<input type="text" data-search-replacement autocomplete="off"></label></div>
      <div class="editor-search-options"><label><input type="checkbox" data-search-case> Match case</label><label><input type="checkbox" data-search-word> Whole identifier</label><label><input type="checkbox" data-search-regex> Regular expression</label><label><input type="checkbox" data-search-selection> Selection only</label></div>
      <div class="editor-search-actions"><button type="button" data-search-action="previous" title="Previous match">↑ Previous</button><button type="button" data-search-action="next" title="Next match">↓ Next</button><button type="button" data-search-action="replace">Replace</button><button type="button" data-search-action="preview">Preview all</button><button type="button" data-search-action="replace-all">Replace all</button><button type="button" data-search-action="close" aria-label="Close search">×</button></div>
      <output data-search-status aria-live="polite"></output><div class="editor-replace-preview" data-search-preview hidden></div>`;
    root.querySelector(".editor-menubar").after(panel);
  }
  panel.classList.toggle("replace-mode", replaceMode);
  panel.dataset.selectionStart = String(initialSelection.start);
  panel.dataset.selectionEnd = String(initialSelection.end);
  const query = panel.querySelector("[data-search-query]");
  const replacement = panel.querySelector("[data-search-replacement]");
  const status = panel.querySelector("[data-search-status]");
  const preview = panel.querySelector("[data-search-preview]");
  query.value ||= editor.dataset.findText || "";
  replacement.value ||= editor.dataset.replaceText || "";

  const scope = () => {
    const selectionOnly = panel.querySelector("[data-search-selection]").checked;
    const start = selectionOnly ? Number(panel.dataset.selectionStart) : 0;
    const end = selectionOnly ? Number(panel.dataset.selectionEnd) : editor.value.length;
    return { start: Math.min(start, end), end: Math.max(start, end) };
  };
  const expression = (global = true) => {
    if (!query.value) return null;
    try {
      const raw = panel.querySelector("[data-search-regex]").checked
        ? query.value
        : query.value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const bounded = panel.querySelector("[data-search-word]").checked
        ? `(?<![A-Za-z0-9_$%])(?:${raw})(?![A-Za-z0-9_$%])`
        : raw;
      return new RegExp(bounded, `${global ? "g" : ""}u${panel.querySelector("[data-search-case]").checked ? "" : "i"}`);
    } catch (error) {
      status.textContent = `Invalid expression: ${error.message}`;
      return null;
    }
  };
  const matches = () => {
    const pattern = expression(true);
    if (!pattern) return [];
    const range = scope();
    return [...editor.value.slice(range.start, range.end).matchAll(pattern)]
      .filter(match => match[0].length)
      .map(match => ({ match, start: range.start + match.index, end: range.start + match.index + match[0].length }));
  };
  const refreshStatus = () => {
    editor.dataset.findText = query.value;
    editor.dataset.replaceText = replacement.value;
    const found = matches();
    status.textContent = query.value ? `${found.length.toLocaleString()} match${found.length === 1 ? "" : "es"}` : "Enter text or an expression to search";
    preview.hidden = true;
    return found;
  };
  const navigate = direction => {
    const found = refreshStatus();
    if (!found.length) return;
    const row = direction > 0
      ? found.find(item => item.start >= editor.selectionEnd) || found[0]
      : [...found].reverse().find(item => item.end <= editor.selectionStart) || found.at(-1);
    editor.focus();
    editor.setSelectionRange(row.start, row.end);
  };
  const replaceOne = () => {
    const found = matches();
    const current = found.find(item => item.start === editor.selectionStart && item.end === editor.selectionEnd)
      || found.find(item => item.start >= editor.selectionEnd) || found[0];
    if (!current) return refreshStatus();
    const pattern = expression(false);
    const value = current.match[0].replace(pattern, replacement.value);
    editor.setRangeText(value, current.start, current.end, "select");
    editor.dispatchEvent(new Event("input", { bubbles: true }));
    refreshStatus();
  };
  const previewAll = () => {
    const found = refreshStatus();
    const pattern = expression(false);
    preview.innerHTML = found.length ? `<strong>Replacement preview</strong>${found.slice(0, 50).map(item => {
      const line = editor.value.slice(0, item.start).split("\n").length;
      return `<div><span>Line ${line}</span><del>${esc(item.match[0])}</del><ins>${esc(item.match[0].replace(pattern, replacement.value))}</ins></div>`;
    }).join("")}${found.length > 50 ? `<small>${(found.length - 50).toLocaleString()} more matches are not shown.</small>` : ""}` : "";
    preview.hidden = !found.length;
  };
  const replaceAll = () => {
    const found = matches();
    if (!found.length) return refreshStatus();
    const range = scope();
    const pattern = expression(true);
    const section = editor.value.slice(range.start, range.end).replace(pattern, replacement.value);
    editor.setRangeText(section, range.start, range.end, "end");
    editor.dispatchEvent(new Event("input", { bubbles: true }));
    toast(`Replaced ${found.length.toLocaleString()} occurrence${found.length === 1 ? "" : "s"}.`);
    refreshStatus();
  };
  panel.querySelectorAll("input").forEach(input => { input.oninput = refreshStatus; input.onchange = refreshStatus; });
  panel.querySelectorAll("[data-search-action]").forEach(button => button.onclick = () => {
    const action = button.dataset.searchAction;
    if (action === "close") { panel.remove(); editor.focus(); }
    else if (action === "previous") navigate(-1);
    else if (action === "next") navigate(1);
    else if (action === "replace") replaceOne();
    else if (action === "preview") previewAll();
    else if (action === "replace-all") replaceAll();
  });
  panel.onkeydown = event => {
    if (event.key === "Escape") { event.preventDefault(); panel.remove(); editor.focus(); }
    else if (event.key === "Enter" && !event.ctrlKey && !event.metaKey) { event.preventDefault(); navigate(event.shiftKey ? -1 : 1); }
  };
  refreshStatus();
  query.focus();
  query.select();
}

function editorChoice(title, message, choices) {
  return new Promise(resolve => {
    const shade = document.createElement("div");
    shade.className = "editor-choice-shade";
    shade.setAttribute("role", "dialog");
    shade.setAttribute("aria-modal", "true");
    shade.setAttribute("aria-labelledby", "editor-choice-title");
    shade.innerHTML = `<section class="editor-choice-card"><h2 id="editor-choice-title">${esc(title)}</h2><p>${esc(message)}</p><div class="modal-actions">${choices.map(choice => `<button type="button" class="button ${choice.className || ""}" data-choice="${esc(choice.value)}">${esc(choice.label)}</button>`).join("")}</div></section>`;
    const finish = value => { shade.remove(); resolve(value); };
    shade.querySelectorAll("[data-choice]").forEach(button => button.onclick = () => finish(button.dataset.choice));
    shade.addEventListener("keydown", event => {
      if (event.key === "Escape") finish("cancel");
      trapFocus(shade, event);
    });
    attachEditorOverlay(shade);
    shade.querySelector('[data-choice="cancel"]')?.focus();
  });
}

function attachEditorOverlay(shade) {
  if (modal.open) modal.append(shade);
  else {
    shade.classList.add("editor-global-overlay");
    document.body.append(shade);
  }
}

function editorProperties(root, pane, path, report) {
  return new Promise(resolve => {
    const metadata = report.metadata || {};
    const shade = document.createElement("div");
    shade.className = "editor-choice-shade";
    shade.setAttribute("role", "dialog");
    shade.setAttribute("aria-modal", "true");
    shade.setAttribute("aria-labelledby", "editor-properties-title");
    const flags = attributeFlags(metadata.attributes ?? metadata.attr ?? 0);
    const flag = (letter, label, hint) => `<label class="check"><input type="checkbox" name="bit-${letter}" ${flags[letter] ? "checked" : ""}> ${label}<small>${hint}</small></label>`;
    const stamp = datestampForInput(metadata.datestamp);
    shade.innerHTML = `<form class="editor-choice-card editor-properties-card"><h2 id="editor-properties-title">File properties</h2><p>Update the directory entry without changing the file bytes.</p>
      <div class="field-grid two">${flag("r", "Read-only", "r · $01")}${flag("h", "Hidden", "h · $02")}${flag("s", "System", "s · $04")}${flag("v", "Volume label", "v · $08")}${flag("d", "Directory", "d · $10")}${flag("a", "Archive", "a · $20")}</div>
      <div class="field"><label>Datestamp</label><input name="datestamp" type="datetime-local" step="2" value="${esc(stamp)}"><small>TOS records the time to the nearest two seconds.</small></div>
      <div class="field"><label>Desktop icon type</label><input name="filetype" value="${esc(metadata.filetype || "")}" placeholder="GEM, TOS or TTP"></div>
      <dl class="editor-property-summary"><dt>Size</dt><dd>${Number(report.size || 0).toLocaleString()} bytes</dd><dt>SHA-256</dt><dd><code>${esc(report.sha256)}</code></dd></dl>
      <div class="modal-actions"><button type="button" class="button ghost" data-properties-cancel>Cancel</button><button type="submit" class="button primary">Apply properties</button></div></form>`;
    const finish = value => { shade.remove(); resolve(value); };
    shade.querySelector("[data-properties-cancel]").onclick = () => finish(null);
    shade.onkeydown = event => {
      if (event.key === "Escape") { event.preventDefault(); finish(null); }
      trapFocus(shade, event);
    };
    shade.querySelector("form").onsubmit = event => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      finish({
        attributes: attributeHex({
          r: form.has("bit-r"), h: form.has("bit-h"), s: form.has("bit-s"),
          v: form.has("bit-v"), d: form.has("bit-d"), a: form.has("bit-a"),
        }),
        datestamp: form.get("datestamp") || "",
        filetype: form.get("filetype") || "",
      });
    };
    modal.append(shade);
    shade.querySelector("[name=bit-r]").focus();
  });
}

function editorProjectManager(project) {
  return new Promise(resolve => {
    const current = structuredClone(project || {});
    const shade = document.createElement("div");
    shade.className = "editor-choice-shade";
    shade.setAttribute("role", "dialog");
    shade.setAttribute("aria-modal", "true");
    shade.innerHTML = `<form class="editor-choice-card editor-project-card"><h2>Editor project metadata</h2><p>Notes, bookmarks, comments and symbols are stored in the private recoverable session, not in the file bytes.</p>
      <div class="field"><label>Project notes</label><textarea name="notes" rows="5">${esc(current.notes || "")}</textarea></div>
      <div class="field"><label>Symbols, one <code>address = label</code> per line</label><textarea name="symbols" rows="6">${esc(Object.entries(current.symbols || {}).map(([address, label]) => `${address} = ${label}`).join("\n"))}</textarea></div>
      <section class="editor-project-bookmarks"><header><strong>Bookmarks</strong><small>${(current.bookmarks || []).length.toLocaleString()}</small></header><div>${(current.bookmarks || []).map((row, index) => `<label><input type="checkbox" name="keepBookmark" value="${index}" checked><code>${Number(row.offset).toLocaleString()}</code><input name="bookmarkName${index}" value="${esc(row.name)}" aria-label="Bookmark name"><input name="bookmarkNote${index}" value="${esc(row.note || "")}" placeholder="Note" aria-label="Bookmark note"></label>`).join("") || "<p>No bookmarks have been saved.</p>"}</div></section>
      <section class="editor-project-comments"><header><strong>Disassembly comments</strong><small>${Object.keys(current.comments || {}).length.toLocaleString()}</small></header><div>${Object.entries(current.comments || {}).map(([offset, comment], index) => `<label><input type="checkbox" name="keepComment" value="${esc(offset)}" checked><code>${Number(offset).toLocaleString()}</code><input name="comment${index}" data-comment-offset="${esc(offset)}" value="${esc(comment)}" aria-label="Comment at offset ${esc(offset)}"></label>`).join("") || "<p>No line comments have been saved.</p>"}</div></section>
      <details class="editor-project-json"><summary>Portable project JSON</summary><textarea name="json" rows="8" spellcheck="false">${esc(JSON.stringify(current, null, 2))}</textarea><button type="button" class="button compact" data-project-load-json>Load JSON into form</button></details>
      <div class="modal-actions"><button type="button" class="button ghost" data-project-cancel>Cancel</button><button type="submit" class="button primary">Save project</button></div></form>`;
    const finish = value => { shade.remove(); resolve(value); };
    const form = shade.querySelector("form");
    shade.querySelector("[data-project-cancel]").onclick = () => finish(null);
    shade.querySelector("[data-project-load-json]").onclick = () => {
      try {
        const parsed = JSON.parse(form.elements.json.value);
        finish(parsed);
      } catch (error) { toast(`Project JSON is invalid: ${error.message}`, true); }
    };
    form.onsubmit = event => {
      event.preventDefault();
      const data = new FormData(form);
      const symbols = {};
      String(data.get("symbols") || "").split(/\n/).forEach(line => {
        const match = line.match(/^\s*([^=]+?)\s*=\s*(\S.*?)\s*$/);
        if (match) symbols[match[1]] = match[2];
      });
      const bookmarks = [...form.querySelectorAll('[name="keepBookmark"]:checked')].map(input => {
        const index = Number(input.value);
        return { ...current.bookmarks[index], name: data.get(`bookmarkName${index}`), note: data.get(`bookmarkNote${index}`) };
      });
      const comments = {};
      [...form.querySelectorAll('[name="keepComment"]:checked')].forEach(input => {
        const field = form.querySelector(`[data-comment-offset="${CSS.escape(input.value)}"]`);
        if (field?.value.trim()) comments[input.value] = field.value.trim();
      });
      finish({ ...current, notes: data.get("notes"), symbols, bookmarks, comments });
    };
    modal.append(shade);
    form.elements.notes.focus();
  });
}

function editorImageSearch(pane) {
  return new Promise(resolve => {
    const shade = document.createElement("div");
    shade.className = "editor-choice-shade";
    shade.setAttribute("role", "dialog");
    shade.setAttribute("aria-modal", "true");
    shade.innerHTML = `<section class="editor-choice-card editor-image-search-card"><header><div><small>IMAGE-WIDE SOURCE SEARCH</small><h2>Search ${esc(pane.image.name)}</h2></div></header><form><input type="search" name="query" placeholder="Filename, command, variable or text" required autocomplete="off"><button type="submit" class="button primary">Search</button><button type="button" class="button ghost" data-image-search-close>Close</button></form><p class="editor-image-search-status" aria-live="polite">Searches filenames and bounded BASIC, command-script and readable text content across the complete mounted filesystem.</p><div class="editor-image-search-results"></div></section>`;
    const finish = value => { shade.remove(); resolve(value); };
    const status = shade.querySelector(".editor-image-search-status");
    const results = shade.querySelector(".editor-image-search-results");
    shade.querySelector("[data-image-search-close]").onclick = () => finish(null);
    shade.querySelector("form").onsubmit = async event => {
      event.preventDefault();
      const query = new FormData(event.currentTarget).get("query");
      status.textContent = "Searching the mounted image…";
      results.replaceChildren();
      try {
        const parameters = fileContextQuery(pane, pane.path, { query, root: "", ...(pane.image.kind === "hd" ? { allPartitions: "true" } : {}) });
        parameters.delete("path");
        const report = await api(`/api/images/${pane.image.id}/inspect/search?${parameters}`);
        status.textContent = `${report.results.length.toLocaleString()} result${report.results.length === 1 ? "" : "s"} · ${report.filesScanned.toLocaleString()} readable files scanned${report.failedReads ? ` · ${report.failedReads.toLocaleString()} unreadable file${report.failedReads === 1 ? "" : "s"} skipped` : ""}${report.skippedLarge ? ` · ${report.skippedLarge.toLocaleString()} large files searched by name only` : ""}${report.unreadableFiles ? ` · ${report.unreadableFiles.toLocaleString()} unreadable file${report.unreadableFiles === 1 ? "" : "s"} skipped` : ""}${report.truncated ? " · result limit reached" : ""}`;
        results.innerHTML = report.results.map((row, index) => `<button type="button" data-image-search-result="${index}"><span class="file-kind-icon ${esc(row.kind)}" aria-hidden="true"></span><b>${esc(row.path)}</b><small>${row.nameMatch ? "Filename match" : `${row.matches.length} content match${row.matches.length === 1 ? "" : "es"}`} · ${humanSize(row.size)}</small>${row.matches.slice(0, 3).map(match => `<code>Line ${match.line}: ${esc(match.text)}</code>`).join("")}</button>`).join("") || '<p class="code-empty-message">No matching files were found.</p>';
        results.querySelectorAll("[data-image-search-result]").forEach(button => button.onclick = () => finish(report.results[Number(button.dataset.imageSearchResult)]));
      } catch (error) { status.textContent = error.message; }
    };
    shade.onkeydown = event => { if (event.key === "Escape") finish(null); else trapFocus(shade, event); };
    modal.append(shade);
    shade.querySelector("[name=query]").focus();
  });
}

function installEditorCloseGuard(root, editor, closeEditor) {
  const closeButton = modal.querySelector(".modal-close");
  const dirty = () => !editor.readOnly && editor.value !== editor.dataset.savedValue;
  const requestClose = async () => {
    if (dirty() && !await confirmChoice("Discard unsaved changes?", "This editor has changes that have not been written back to the image.", { confirmLabel: "Close and discard", danger: true })) return;
    if (dirty()) {
      editor.value = editor.dataset.savedValue;
      captureActiveEditorDocument();
    }
    closeEditor();
  };
  const interceptClose = event => {
    if (!root.isConnected) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    requestClose();
  };
  const interceptCancel = event => {
    if (!root.isConnected || !dirty()) return;
    event.preventDefault();
    requestClose();
  };
  closeButton.addEventListener("click", interceptClose, true);
  modal.addEventListener("cancel", interceptCancel);
  modal.addEventListener("close", () => {
    closeButton.removeEventListener("click", interceptClose, true);
    modal.removeEventListener("cancel", interceptCancel);
  }, { once: true });
  return requestClose;
}

async function loadEditorProject(pane, path) {
  const query = fileContextQuery(pane, path);
  return (await api(`/api/images/${pane.image.id}/editor-project?${query}`)).project;
}

async function saveEditorProject(pane, path, project) {
  return (await api(`/api/images/${pane.image.id}/editor-project`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, partition: pane.partition, side: pane.side, project }),
  })).project;
}

function editorEmulatorQuery(pane, path, isBasic) {
  return fileContextQuery(pane, path, {
    basic: isBasic ? "true" : "false",
    hardwareProfile: JSON.stringify(editorTargetProfile(pane)),
  });
}

async function chooseEditorEmulatorLaunch(status, entry, isBasic, purpose = "run") {
  const choices = [{ value: "cancel", label: "Cancel", className: "ghost" }];
  if (status.parentMountable) {
    choices.push({ value: "parent-mount", label: "Mount parent only" });
    choices.push({ value: "parent-auto", label: "Mount and boot parent" });
  }
  if (isBasic && status.isolatedBasic) choices.push({ value: "isolated-basic", label: `${purpose === "debug" ? "Inject and debug" : "Inject and run"} BASIC buffer`, className: "primary" });
  if (choices.length === 1) {
    await editorChoice(`${purpose === "debug" ? "Debugger" : "Emulator"} unavailable`, status.parentMessage || status.message || "The selected emulator cannot launch this image or file.", choices);
    return "cancel";
  }
  const parentNote = status.parentMountable
    ? "The parent choices preserve access to the program's companion files. Mount only stops at the machine prompt; Mount and boot parent follows that image's normal boot sequence."
    : `The parent image cannot be mounted: ${status.parentMessage || "unsupported media."}`;
  const basicNote = isBasic && status.isolatedBasic
    ? ` The current “${entry.name}” editor buffer, including unsaved changes, can instead be tokenised, injected into a temporary bootable disk as PROGRAM, and started automatically. That isolated run cannot provide companion files from the parent image.`
    : "";
  return editorChoice(
    `${purpose === "debug" ? "Debug" : "Run"} with ${status.label}`,
    `${parentNote}${basicNote}`,
    choices,
  );
}

function openBrowserEmulator(pane, result) {
  const shade = document.createElement("div");
  shade.className = "editor-choice-shade emulator-viewer-shade";
  shade.setAttribute("role", "dialog");
  shade.setAttribute("aria-modal", "true");
  const port = Number(result.viewerPort || 8668);
  const viewer = `${location.protocol}//${location.hostname}:${port}/vnc.html?autoconnect=true&resize=scale&path=websockify`;
  shade.innerHTML = `<section class="editor-choice-card emulator-viewer"><header><div><small>LIVE MANAGED EMULATOR</small><h2>${esc(result.emulator || "Atari emulator")}</h2></div><div><button type="button" class="button" data-emulator-fullscreen>Full screen</button><button type="button" class="button danger" data-emulator-stop>Stop and close</button></div></header><p>${esc(result.summary || "The configured emulator is running below. Click the display before typing.")}</p><iframe src="${esc(viewer)}" title="${esc(result.emulator || "Atari emulator")} display" allow="clipboard-read; clipboard-write" referrerpolicy="no-referrer"></iframe></section>`;
  const stop = async () => {
    shade.querySelectorAll("button").forEach(button => { button.disabled = true; });
    try { await api(`/api/images/${pane.image.id}/editor-emulator`, { method: "DELETE" }); }
    catch (error) { toast(error.message, true); }
    shade.remove();
  };
  shade.querySelector("[data-emulator-stop]").onclick = stop;
  shade.querySelector("[data-emulator-fullscreen]").onclick = () => shade.querySelector("iframe").requestFullscreen?.();
  shade.onkeydown = event => { if (event.key === "Escape") stop(); };
  attachEditorOverlay(shade);
}

function showInteractiveEmulator(pane, result) {
  if (result.displayMode === "native") {
    toast(result.summary || `${result.emulator || "The emulator"} is running in a desktop window.`);
    return;
  }
  openBrowserEmulator(pane, result);
}

function paneEmulatorTarget(index) {
  const pane = panes[index];
  // A hard drive is attached whole, exactly as it would be on the machine;
  // anything else is handed over as the image the pane has open.
  return pane.image.kind === "hd"
    ? { partition: null, label: `complete hard drive · ${pane.image.name}`, modePrefix: "whole-drive" }
    : { partition: pane.partition, label: pane.image.name, modePrefix: "parent" };
}

async function launchPaneEmulator(index, debug = false) {
  const pane = panes[index];
  const target = paneEmulatorTarget(index);
  const endpoint = debug ? "editor-debugger" : "editor-emulator";
  const query = new URLSearchParams({
    hardwareProfile: JSON.stringify(editorTargetProfile(pane)),
  });
  if (target.partition != null) query.set("partition", target.partition);
  const status = await api(`/api/images/${pane.image.id}/${endpoint}?${query}`);
  if (!status.available) {
    await editorChoice(
      `${debug ? "Debugger" : "Emulator"} unavailable`,
      status.parentMessage || status.message || `The configured emulator cannot mount ${target.label}.`,
      [{ value: "cancel", label: "Close", className: "primary" }],
    );
    return false;
  }
  const action = await editorChoice(
    `${debug ? "Debug" : "Run"} ${target.label}`,
    `${status.label} can mount this media. Choose whether to leave the machine at its command prompt or follow the image's normal boot sequence.${target.modePrefix === "whole-drive" ? " The drive is attached from an isolated snapshot, so emulator writes do not reach the working image." : ""}`,
    [
      { value: "cancel", label: "Cancel", className: "ghost" },
      { value: "mount", label: "Mount only" },
      { value: "auto", label: debug ? "Mount and start debugger" : "Mount and boot", className: "primary" },
    ],
  );
  if (action === "cancel") return false;
  const body = {
    path: "", partition: target.partition, side: pane.side,
    mode: `${target.modePrefix}-${action}`,
    interactive: true,
    hardwareProfile: editorTargetProfile(pane),
  };
  if (debug) body.action = "launch";
  const response = await api(`/api/images/${pane.image.id}/${endpoint}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  showInteractiveEmulator(pane, response.result);
  return true;
}

async function runFileInConfiguredEmulator(pane, entry, path, target = null, isBasic = false, source = "") {
  if (target) {
    toast("Extract this archive member before handing it to an emulator.", true);
    return null;
  }
  try {
    const status = await api(`/api/images/${pane.image.id}/editor-emulator?${editorEmulatorQuery(pane, path, isBasic)}`);
    if (!status.available) {
      await editorChoice("Emulator unavailable", status.message, [{ value: "cancel", label: "Close", className: "primary" }]);
      return null;
    }
    const mode = await chooseEditorEmulatorLaunch(status, entry, isBasic, "run");
    if (mode === "cancel") return null;
    const result = await api(`/api/images/${pane.image.id}/editor-emulator`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, partition: pane.partition, side: pane.side, mode, interactive: true, source: isBasic ? source : undefined, hardwareProfile: editorTargetProfile(pane) }),
    });
    if (result.result.interactive) showInteractiveEmulator(pane, result.result);
    else toast(result.result.bounded ? "The managed emulator completed its compatibility-check window." : `Emulator finished with return code ${result.result.returnCode}.`);
    return result;
  } catch (error) {
    await editorChoice("The emulator could not run", error.message, [{ value: "cancel", label: "Close", className: "primary" }]);
    return null;
  }
}

function editorTestResultsMarkup(project) {
  const tests = [...(project?.tests || [])].reverse();
  const launchLabels = { "isolated-basic": "isolated BASIC test disk", "parent-auto": "parent image with autoboot", "parent-mount": "parent image mounted only" };
  return tests.length ? `<div class="editor-test-results">${tests.map(result => `<article class="${Number(result.returnCode) === 0 ? "pass" : "fail"}"><header><b>${esc(result.emulator || (result.kind === "debugger" ? "Debugger" : "Emulator"))}</b><time>${esc(result.time || "")}</time><strong>${result.bounded ? "Expected test window complete" : `Return ${Number(result.returnCode)}`}</strong></header>${result.summary ? `<p>${esc(result.summary)}</p>` : ""}${result.launchMode ? `<small>${esc(launchLabels[result.launchMode] || result.launchMode)}${result.machine ? ` · ${esc(result.machine)}` : ""}</small>` : ""}${result.breakpoint ? `<small>Breakpoint ${esc(result.breakpoint)}</small>` : ""}${result.stdout ? `<details open><summary>Program output</summary><pre>${esc(result.stdout)}</pre></details>` : ""}${result.stderr ? `<details open><summary>Diagnostic output</summary><pre>${esc(result.stderr)}</pre></details>` : ""}</article>`).join("")}</div>` : '<p class="code-empty-message">No emulator or debugger runs have been retained for this file.</p>';
}

async function openDebuggerWorkspace(pane, entry, path, architecture = "68000", initialBreakpoint = "", isBasic = false, source = "") {
  const status = await api(`/api/images/${pane.image.id}/editor-debugger?${editorEmulatorQuery(pane, path, isBasic)}`);
  if (!status.available) {
    await editorChoice("Debugger unavailable", status.message, [{ value: "cancel", label: "Close", className: "primary" }]);
    return;
  }
  const launchMode = await chooseEditorEmulatorLaunch(status, entry, isBasic, "debug");
  if (launchMode === "cancel") return;
  const shade = document.createElement("div");
  shade.className = "editor-choice-shade";
  shade.setAttribute("role", "dialog");
  shade.setAttribute("aria-modal", "true");
  shade.innerHTML = `<section class="editor-choice-card debugger-workspace"><header><div><small>EXTERNAL EMULATOR ADAPTER</small><h2>Debug ${esc(entry.name)}</h2></div></header><p>${esc(status.message)}</p><div class="field-grid two"><div class="field"><label>Breakpoint or address</label><input name="debugBreakpoint" value="${esc(initialBreakpoint)}" spellcheck="false"></div><div class="field"><label>Expression or memory range</label><input name="debugExpression" placeholder="register, address or adapter expression" spellcheck="false"></div></div><div class="debugger-actions">${(status.actions || []).map(action => `<button type="button" class="button ${action === "launch" ? "primary" : ""}" data-debugger-action="${esc(action)}">${esc(action[0].toUpperCase() + action.slice(1))}</button>`).join("")}</div><pre class="debugger-transcript" aria-live="polite">Ready. Each control invokes the configured adapter with its action placeholder.\n</pre><div class="modal-actions"><button type="button" class="button ghost" data-debugger-close>Close</button></div></section>`;
  const transcript = shade.querySelector(".debugger-transcript");
  const close = () => shade.remove();
  shade.querySelector("[data-debugger-close]").onclick = close;
  shade.querySelectorAll("[data-debugger-action]").forEach(button => button.onclick = async () => {
    const action = button.dataset.debuggerAction;
    const buttons = [...shade.querySelectorAll("[data-debugger-action]")];
    buttons.forEach(control => { control.disabled = true; });
    transcript.textContent += `\n> ${action}\n`;
    try {
      const result = await api(`/api/images/${pane.image.id}/editor-debugger`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path, partition: pane.partition, side: pane.side, action, architecture,
          mode: launchMode, source: isBasic ? source : undefined,
          interactive: true,
          hardwareProfile: editorTargetProfile(pane),
          breakpoint: shade.querySelector("[name=debugBreakpoint]").value,
          expression: shade.querySelector("[name=debugExpression]").value,
        }),
      });
      if (result.result.interactive) {
        transcript.textContent += `[interactive ${result.result.emulator} started]\n`;
        showInteractiveEmulator(pane, result.result);
      } else transcript.textContent += `${result.result.stdout || ""}${result.result.stderr ? `\n${result.result.stderr}` : ""}\n[return ${result.result.returnCode}]\n`;
      transcript.scrollTop = transcript.scrollHeight;
    } catch (error) { transcript.textContent += `[error] ${error.message}\n`; }
    finally { buttons.forEach(control => { control.disabled = false; }); }
  });
  shade.onkeydown = event => { if (event.key === "Escape") close(); else trapFocus(shade, event); };
  modal.append(shade);
  shade.querySelector("[name=debugBreakpoint]").focus();
}

function bytePreviewMarkup(report) {
  const bytes = String(report?.data || "").match(/../g) || [];
  const ascii = bytes.map(value => {
    const number = Number.parseInt(value, 16);
    return number >= 32 && number <= 126 ? String.fromCharCode(number) : ".";
  }).join("");
  return `<code>${bytes.join(" ") || "No bytes"}</code><span>${esc(ascii)}</span>`;
}

function installSourceEditorControls(index, pane, entry, path, report, canEdit, isBasic, target = null, intelligence = null) {
  const root = modalContent.querySelector(".source-editor");
  installEditorMenuDismissal(root);
  const editor = root.querySelector(".source-content");
  const requestClose = installEditorCloseGuard(root, editor, () => modal.close());
  const saveButton = root.querySelector(".editor-save-submit");
  let project = report.project || null;
  let lineRanges = [];
  let synchronizedBytes = false;
  let syncTimer = null;
  const syncPanel = root.querySelector(".source-byte-sync");
  const ensureProject = async () => project || (project = await loadEditorProject(pane, path));
  const ensureBasicLineRanges = async () => {
    if (!isBasic || lineRanges.length) return;
    const verified = await api(`/api/images/${pane.image.id}/inspect/basic/verify`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: editor.dataset.savedValue || editor.value }),
    });
    lineRanges = verified.lineRanges || [];
  };
  const sourceByteOffset = async () => {
    if (!isBasic) return editor.selectionStart;
    await ensureBasicLineRanges();
    const lineText = editor.value.slice(0, editor.selectionStart).split("\n").at(-1) || "";
    const number = Number(lineText.match(/^\s*(\d+)/)?.[1]);
    return lineRanges.find(row => Number(row.line) === number)?.start ?? null;
  };
  const updateSynchronizedBytes = async () => {
    if (!synchronizedBytes || !syncPanel || target) return;
    try {
      const offset = await sourceByteOffset();
      if (offset == null) {
        syncPanel.innerHTML = "<span>This unsaved BASIC line has no saved byte range yet.</span>";
        return;
      }
      const bytes = await api(`/api/images/${pane.image.id}/file-hex?${fileContextQuery(pane, path, { offset, length: 32 })}`);
      syncPanel.innerHTML = `<header><strong>Saved bytes at file offset ${Number(bytes.offset).toLocaleString()}</strong><button type="button" title="Open this location in the full hex editor">Open Hex</button></header>${bytePreviewMarkup(bytes)}`;
      syncPanel.querySelector("button").onclick = () => openFileHexEditor(index, entry, path, modalContent, bytes.offset, target);
    } catch (error) { syncPanel.innerHTML = `<span>${esc(error.message || String(error))}</span>`; }
  };
  const save = async () => {
    if (editor.readOnly || editor.value === editor.dataset.savedValue) return;
    if (!target && intelligence?.history) {
      const changes = intelligence.history();
      if (changes.length) {
        const current = await ensureProject();
        current.history = [...(current.history || []), ...changes];
        project = await saveEditorProject(pane, path, current);
        changes.splice(0, changes.length);
      }
    }
    modal.querySelector("form").requestSubmit(saveButton);
  };
  const saveAs = async () => {
    if (editor.readOnly) return;
    const rule = targetNameRule(pane, entry.name);
    const suffix = entry.name.length < rule.limit ? "2" : "";
    const suggested = `${entry.name.slice(0, rule.limit - suffix.length)}${suffix}`;
    const newName = await promptValue("Save a copy beside this file", "New filename", { value: suggested, message: `A new ${rule.label} file is written next to ${entry.name}, leaving the original as it is.`, maxlength: rule.limit, confirmLabel: "Save copy", note: `Maximum ${rule.limit} characters.` });
    if (newName == null) return;
    try {
      const data = await api(`/api/images/${pane.image.id}/inspect`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, partition: pane.partition, side: pane.side, text: editor.value, basic: isBasic, sha256: report.sha256, newName })
      });
      pane.image = data.image;
      await loadDirectory(index);
      modal.close();
      toast(`${newName} created with the original Atari metadata. An undo checkpoint is available.`);
    } catch (error) { toast(error.message, true); }
  };
  const insertPaste = async text => {
    let inserted = text;
    if (isBasic) {
      const choice = await editorChoice(
        "Paste into ST BASIC",
        "Choose whether to validate numbered BASIC source or insert the clipboard exactly as plain text. The complete program must be valid BASIC before it can be saved.",
        [
          { value: "cancel", label: "Cancel", className: "ghost" },
          { value: "plain", label: "Paste plain text" },
          { value: "basic", label: "Paste as BASIC source", className: "primary" },
        ],
      );
      if (choice === "cancel") return;
      if (choice === "basic") {
        try {
          const result = await api(`/api/images/${pane.image.id}/inspect/basic/normalise`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
          });
          inserted = result.text;
        } catch (error) { return toast(error.message, true); }
      }
    }
    editor.setRangeText(inserted, editor.selectionStart, editor.selectionEnd, "end");
    editor.dispatchEvent(new Event("input", { bubbles: true }));
    editor.focus();
  };
  const replaceSelection = async mode => {
    try {
      if (mode === "copy" || mode === "cut") {
        const text = editor.value.slice(editor.selectionStart, editor.selectionEnd);
        if (text) await navigator.clipboard.writeText(text);
        if (mode === "cut" && canEdit && text) editor.setRangeText("", editor.selectionStart, editor.selectionEnd, "end");
      } else if (mode === "paste" && canEdit) {
        await insertPaste(await navigator.clipboard.readText());
        return;
      }
      editor.dispatchEvent(new Event("input", { bubbles: true }));
      editor.focus();
    } catch (_error) { toast("Clipboard access was refused by the browser. Use the keyboard shortcut instead.", true); }
  };
  root.querySelectorAll(".editor-menu").forEach(menu => menu.addEventListener("toggle", () => {
    if (menu.open) closeEditorMenus(root, menu);
  }));
  root.querySelectorAll("[data-editor-action]").forEach(control => control.addEventListener("click", async event => {
    event.preventDefault();
    const action = control.dataset.editorAction;
    closeEditorMenus(root);
    if (action === "save") save();
    else if (action === "save-as") await saveAs();
    else if (action === "export") downloadDocument(`${entry.name}.txt`, editor.value, "text/plain;charset=utf-8");
    else if (action === "properties") {
      const properties = await editorProperties(root, pane, path, report);
      if (!properties) return;
      const data = await api(`/api/images/${pane.image.id}/inspect/properties`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, partition: pane.partition, side: pane.side, sha256: report.sha256, ...properties }),
      });
      pane.image = data.image;
      report.metadata = data.inspection.metadata;
      report.sha256 = data.inspection.sha256;
      await loadDirectory(index);
      toast(`${entry.name} properties updated without changing its bytes.`);
    }
    else if (action === "close") requestClose();
    else if (["copy", "cut", "paste"].includes(action)) await replaceSelection(action);
    else if (action === "select-all") { editor.focus(); editor.select(); updateSourceEditorStatus(root); }
    else if (action === "find") openEditorSearch(root, editor, false);
    else if (action === "find-replace") openEditorSearch(root, editor, true);
    else if (action === "search-image") {
      const result = await editorImageSearch(pane);
      if (!result) return;
      if (result.partition != null) pane.partition = Number(result.partition);
      if (result.side != null) pane.side = Number(result.side);
      pane.path = parentPath(result.path);
      const leaf = result.path.split(/[\\/]/).at(-1) || result.name;
      await loadDirectory(index);
      await openFileEditor(index, leaf, null, result.path);
    }
    else if (action === "find-references") intelligence?.findReferences();
    else if (action === "rename-symbol") intelligence?.renameSymbol();
    else if (action === "go-to-line") intelligence?.goToLine();
    else if (action === "complete") intelligence?.showCompletions();
    else if (action === "line-duplicate") intelligence?.lineOperation("duplicate");
    else if (action === "line-up") intelligence?.lineOperation("move-up");
    else if (action === "line-down") intelligence?.lineOperation("move-down");
    else if (action === "line-join") intelligence?.lineOperation("join");
    else if (action === "line-delete") intelligence?.lineOperation("delete");
    else if (action === "fold-toggle-all") intelligence?.toggleAll();
    else if (action === "sync-bytes") {
      synchronizedBytes = !synchronizedBytes;
      syncPanel.hidden = !synchronizedBytes;
      control.querySelector("span").textContent = synchronizedBytes ? "Hide synchronized bytes" : "Show synchronized bytes";
      if (synchronizedBytes) await updateSynchronizedBytes();
    }
    else if (action === "condense-code") await intelligence?.condense();
    else if (action === "refactor-code") await intelligence?.refactor();
    else if (action === "structure-guides") intelligence?.toggleStructureGuides(root.querySelector("[data-structure-guide-size]")?.value);
    else if (action === "toggle-comment") intelligence?.toggleComment();
    else if (action === "normalise-commands") intelligence?.normaliseCommands();
    else if (action === "format-code") await intelligence?.formatCode();
    else if (action === "verify-basic") await intelligence?.verifyRoundTrip();
    else if (action === "program-outline") intelligence?.showOutline();
    else if (action === "dependencies") {
      const report = await api(`/api/images/${pane.image.id}/dependencies?${fileContextQuery(pane, path)}`);
      intelligence?.showCustom("Cross-file dependencies", `<p class="code-empty-message">Indexed ${Number(report.filesIndexed || 0).toLocaleString()} files. ${report.safeForSubdirectory ? "Every direct dependency was resolved without a rooted path." : "Review unresolved, ambiguous or root-relative references before moving this launcher."}</p><div class="code-dependency-list">${report.dependencies.map(row => `<article class="${row.resolved && !row.ambiguous ? "resolved" : "warning"}"><b>${esc(row.action)} ${esc(row.target)}</b><span>${row.path ? esc(row.path) : row.ambiguous ? `${row.candidates.length} possible files` : "Not found"}</span>${row.rootRelative ? "<small>Root-relative reference</small>" : ""}</article>`).join("") || "<p>No direct CHAIN, EXEC, RUN, LOAD, DIR or LIB references were found.</p>"}</div>`);
    }
    else if (action === "cheat-candidates") await showEditorCheatCandidates(root, intelligence, pane, path, false, target);
    else if (action === "editor-history") intelligence?.showHistory();
    else if (action === "compare-saved") intelligence?.compareWith(editor.dataset.savedValue || "");
    else if (action === "project-notes") {
      if (target) return toast("Archive-member project notes become available after extracting the member into an image.", true);
      const current = await ensureProject();
      const notes = await promptValue("Project notes", "Notes", { value: current.notes || "", message: "Notes are stored in the private recoverable session, not in the file bytes.", confirmLabel: "Save notes", required: false, trim: false });
      if (notes != null) { current.notes = notes; project = await saveEditorProject(pane, path, current); toast("Project notes saved."); }
    }
    else if (action === "project-bookmark") {
      if (target) return toast("Extract this archive member before adding project bookmarks.", true);
      const current = await ensureProject();
      const offset = await sourceByteOffset();
      if (offset == null) return toast("Save this new or renumbered BASIC line before bookmarking its byte offset.", true);
      const name = await promptValue("Add a bookmark", "Bookmark name", { value: isBasic ? `BASIC line ${editor.value.slice(0, editor.selectionStart).split("\n").at(-1)?.match(/^\s*(\d+)/)?.[1] || "cursor"}` : `Offset ${offset}`, message: `The bookmark points at saved-file offset ${offset}.`, confirmLabel: "Add bookmark" });
      if (name) { current.bookmarks = [...(current.bookmarks || []), { offset, name, note: "" }]; project = await saveEditorProject(pane, path, current); toast("Bookmark saved."); }
    }
    else if (action === "project-manage") {
      if (target) return toast("Extract this archive member before managing project metadata.", true);
      const current = await ensureProject();
      const edited = await editorProjectManager(current);
      if (edited) { project = await saveEditorProject(pane, path, edited); toast("Editor project metadata saved."); }
    }
    else if (action === "run-emulator") {
      const result = await runFileInConfiguredEmulator(pane, entry, path, target, isBasic, editor.value);
      if (result) { project = result.project; intelligence?.showCustom("Emulator result", editorTestResultsMarkup(project)); }
    }
    else if (action === "debugger-workspace") {
      if (target) return toast("Extract this archive member before starting a debugger.", true);
      // A GEMDOS program is relocatable and records no address, so the
      // debugger starts at the beginning of the extracted bytes.
      await openDebuggerWorkspace(pane, entry, path, pane.image?.targetHardware === "tos" ? "68040" : "68000", "0x0", isBasic, editor.value);
      project = await loadEditorProject(pane, path);
    }
    else if (action === "project-tests") intelligence?.showCustom("Emulator and debugger results", editorTestResultsMarkup(await ensureProject()));
    else if (action === "undo" || action === "redo") {
      editor.focus();
      if (!intelligence?.[action]?.()) document.execCommand(action);
      updateSourceEditorStatus(root);
    }
    else if (action === "hex") openFileHexEditor(index, entry, path, modalContent, 0, target);
    else if (action === "help-overview") intelligence?.overview();
    else if (action === "help-reference") intelligence?.reference();
    else if (action === "help-problems") intelligence?.showProblems();
    else if (action === "help-symbols") intelligence?.showSymbols();
  }));
  root.querySelector("[data-structure-guide-size]")?.addEventListener("change", event => intelligence?.setStructureGuideSize(event.target.value));
  editor.addEventListener("input", () => {
    lineRanges = [];
    updateSourceEditorStatus(root);
  });
  if (isBasic && canEdit) editor.addEventListener("paste", event => {
    event.preventDefault();
    insertPaste(event.clipboardData.getData("text"));
  });
  editor.addEventListener("keyup", () => updateSourceEditorStatus(root));
  editor.addEventListener("click", () => updateSourceEditorStatus(root));
  const scheduleSync = () => { clearTimeout(syncTimer); syncTimer = setTimeout(updateSynchronizedBytes, 100); };
  editor.addEventListener("click", scheduleSync);
  editor.addEventListener("keyup", scheduleSync);
  root.addEventListener("keydown", event => {
    if (!(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLocaleLowerCase();
    if (key === "z" && !event.shiftKey && intelligence?.undo?.()) { event.preventDefault(); updateSourceEditorStatus(root); }
    else if ((key === "y" || (key === "z" && event.shiftKey)) && intelligence?.redo?.()) { event.preventDefault(); updateSourceEditorStatus(root); }
    else if (key === "s") { event.preventDefault(); event.shiftKey ? saveAs() : save(); }
    else if (key === "w") { event.preventDefault(); requestClose(); }
    else if (key === "f") { event.preventDefault(); openEditorSearch(root, editor, false); }
    else if (key === "h" && canEdit) { event.preventDefault(); openEditorSearch(root, editor, true); }
    else if (key === "g") { event.preventDefault(); intelligence?.goToLine(); }
    else if (key === "/" && isBasic && canEdit) { event.preventDefault(); intelligence?.toggleComment(); }
  });
  updateSourceEditorStatus(root);
}

// `start` and `length` are empty by default rather than 0 and 8192, so that
// the first listing of a file lets the decoder choose. For an Atari program
// that means starting at the code instead of at the 28-byte header. The boxes
// are then filled in from what came back, so the reader can see the offset and
// change it.
async function renderDisassemblyEditor(index, entry, path, inspection, architecture = "auto", origin = "", start = "", length = "", focusOffset = null, target = null) {
  const pane = panes[index];
  if (!target) retainEditorDocument(index, pane, entry, path, "disassembly");
  const query = new URLSearchParams({
    ...(target?.context || Object.fromEntries(fileContextQuery(pane, path))),
    architecture, origin, start, length,
  });
  const report = await api(`${target?.disassemblyEndpoint || `/api/images/${pane.image.id}/disassembly`}?${query}`);
  const downloadUrl = target ? "" : fileDownloadUrl(pane, path);
  const exportUrl = target?.exportUrl || fileExportUrl(pane, path);
  if (!replaceAnalysisLoading(`<div class="analysis-dialog file-inspector disassembly-editor"><header><div><small>${esc(report.architecture.toUpperCase())} DISASSEMBLY · ${humanSize(report.size)}</small><h2>${esc(entry.name)}</h2></div></header>
    ${disassemblyMenus(downloadUrl, exportUrl, target ? "Export original archive member…" : "Export original binary…")}
    <div class="disassembly-controls">
      <label>Processor<select name="architecture">${["68000", "68010", "68020", "68030", "68040", "68060"].map(target => `<option value="${target}" ${report.architecture === target ? "selected" : ""}>MC${target}</option>`).join("")}</select></label>
      <label>Origin<input name="origin" value="0x${Number(report.origin).toString(16).toUpperCase()}"></label>
      <label>File offset<input name="start" value="${Number(report.start)}"></label>
      <label>Bytes<input name="length" value="${Number(length) || Math.max(0, Number(report.end) - Number(report.start)) || 8192}"></label>
      <button class="button small disassembly-refresh" type="button">Disassemble</button>
    </div>
    <div class="disassembly-source" style="${disassemblyColumnStyle(report)}" role="textbox" aria-readonly="true" aria-label="Disassembled source"><div class="disassembly-source-head" aria-hidden="true"><span></span><span>Address</span><span>Bytes</span><span>Instruction</span><span>Annotation</span></div>${disassemblySource(report)}</div>
    <aside class="disassembly-byte-sync" aria-live="polite" hidden></aside>
    <details class="disassembly-strings"><summary>Readable strings (${report.strings.length})</summary><div>${report.strings.map(item => `<button type="button" data-string-offset="${Number(item.offset)}" title="Go to this location in the disassembly"><code>&amp;${Number(item.address).toString(16).toUpperCase()}</code><span>${esc(item.text)}</span></button>`).join("") || "<p>No human-looking text strings were found.</p>"}</div></details>
    ${report.truncated || report.limited ? '<div class="help-warning">Only the requested section is shown. Change File offset or Bytes to inspect another region.</div>' : ""}
    <footer class="editor-status"><span>Read-only</span><span>${report.rows.length.toLocaleString()} decoded lines · comments appear beside their instruction</span><span>${esc(report.architectureReason)}</span></footer></div>`)) return;
  const root = modalContent.querySelector(".disassembly-editor");
  installEditorMenuDismissal(root);
  const source = root.querySelector(".disassembly-source");
  installEditorWindow(root);
  if (!target) installEditorDocumentTabs(root, pane);
  const intelligence = window.AtariCodeEditor?.enhanceDisassembly({ root, report, targetProfile: editorTargetProfile(pane) });
  modalContent.querySelector(".disassembly-refresh").onclick = async () => {
    const values = Object.fromEntries(new FormData(modalContent.closest("form")));
    analysisLoading("Disassembling file", path);
    try { await renderDisassemblyEditor(index, entry, path, inspection, values.architecture, values.origin, values.start, values.length, null, target); }
    catch (error) { toast(error.message, true); modal.close(); }
  };
  root.querySelectorAll(".editor-menu").forEach(menu => menu.addEventListener("toggle", () => {
    if (menu.open) closeEditorMenus(root, menu);
  }));
  const selectSource = () => {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(source);
    selection.removeAllRanges();
    selection.addRange(range);
  };
  const findSource = async () => {
    const needle = await promptValue("Find in disassembly", "Text to find", { placeholder: "Instruction, label or comment", confirmLabel: "Find" });
    if (!needle) return;
    const line = [...root.querySelectorAll(".disassembly-source-line")].find(item => item.textContent.toLocaleLowerCase().includes(needle.toLocaleLowerCase()));
    root.querySelectorAll(".disassembly-source-line.found").forEach(item => item.classList.remove("found"));
    if (!line) return toast(`“${needle}” was not found.`, true);
    line.classList.add("found");
    line.scrollIntoView({ block: "center" });
    line.focus();
  };
  let project = report.project || { symbols: {}, regions: [], bookmarks: [], comments: {}, history: [], notes: "", tests: [] };
  let selectedLines = [];
  let selectionAnchor = null;
  let synchronizedBytes = false;
  const syncPanel = root.querySelector(".disassembly-byte-sync");
  const sourceLines = () => [...root.querySelectorAll(".disassembly-source-line")];
  const reportRow = element => report.rows.find(row => Number(row.offset) === Number(element?.dataset.offset));
  const setSelectedLines = lines => {
    selectedLines = lines;
    sourceLines().forEach(line => line.classList.toggle("project-selected", selectedLines.includes(line)));
  };
  const updateDisassemblyBytes = async () => {
    if (!synchronizedBytes || !syncPanel || !selectedLines[0]) return;
    try {
      const offset = Number(selectedLines[0].dataset.offset);
      const endpoint = target?.hexEndpoint || `/api/images/${pane.image.id}/file-hex`;
      const context = target?.context || Object.fromEntries(fileContextQuery(pane, path));
      const bytes = await api(`${endpoint}?${new URLSearchParams({ ...context, offset, length: 32 })}`);
      syncPanel.innerHTML = `<header><strong>Bytes at file offset ${Number(bytes.offset).toLocaleString()}</strong><button type="button">Open Hex</button></header>${bytePreviewMarkup(bytes)}`;
      syncPanel.querySelector("button").onclick = () => openFileHexEditor(index, entry, path, modalContent, bytes.offset, target);
    } catch (error) { syncPanel.innerHTML = `<span>${esc(error.message || String(error))}</span>`; }
  };
  sourceLines().forEach((line, lineIndex, allLines) => line.addEventListener("click", event => {
    if (event.shiftKey && selectionAnchor != null) {
      const first = Math.min(selectionAnchor, lineIndex); const last = Math.max(selectionAnchor, lineIndex);
      setSelectedLines(allLines.slice(first, last + 1));
    } else {
      selectionAnchor = lineIndex;
      setSelectedLines([line]);
    }
    updateDisassemblyBytes();
  }));
  const selectedRange = () => {
    const rows = selectedLines.map(reportRow).filter(Boolean);
    if (!rows.length) return null;
    const startOffset = Math.min(...rows.map(row => Number(row.offset)));
    const endOffset = Math.max(...rows.map(row => Number(row.offset) + Math.max(1, String(row.bytes || "").split(/\s+/).filter(Boolean).length)));
    return { start: startOffset, end: endOffset, rows };
  };
  const inspectSelectedData = async () => {
    const range = selectedRange();
    if (!range) return toast("Select one or more disassembly lines first.", true);
    const length = Math.min(4096, Math.max(1, range.end - range.start));
    const endpoint = target?.hexEndpoint || `/api/images/${pane.image.id}/file-hex`;
    const context = target?.context || Object.fromEntries(fileContextQuery(pane, path));
    const page = await api(`${endpoint}?${new URLSearchParams({ ...context, offset: range.start, length })}`);
    const values = String(page.data || "").match(/../g)?.map(value => Number.parseInt(value, 16)) || [];
    const ascii = values.map(value => value >= 32 && value < 127 ? String.fromCharCode(value) : ".").join("");
    const littleWords = [];
    const bigWords = [];
    for (let offset = 0; offset + 1 < values.length && littleWords.length < 64; offset += 2) {
      littleWords.push(`&${(values[offset] | values[offset + 1] << 8).toString(16).toUpperCase().padStart(4, "0")}`);
      bigWords.push(`&${(values[offset] << 8 | values[offset + 1]).toString(16).toUpperCase().padStart(4, "0")}`);
    }
    const pixels = values.slice(0, 512).flatMap(value => Array.from({ length: 8 }, (_item, bit) => (value & (0x80 >> bit)) ? 1 : 0));
    intelligence?.showCustom("Selected data inspector", `<div class="code-data-inspector"><p>File offsets ${range.start.toLocaleString()} to ${(range.start + values.length - 1).toLocaleString()} · ${values.length.toLocaleString()} bytes${length < range.end - range.start ? " · preview bounded to 4 KiB" : ""}</p><details open><summary>Text and byte view</summary><code>${esc(ascii)}</code><code>${values.map(value => value.toString(16).toUpperCase().padStart(2, "0")).join(" ")}</code></details><details><summary>16-bit words</summary><h4>Little endian</h4><code>${littleWords.join(" ")}</code><h4>Big endian</h4><code>${bigWords.join(" ")}</code></details><details><summary>1 bit-per-pixel preview</summary><div class="code-bitmap-preview" style="--bitmap-columns:64">${pixels.map(value => `<i class="${value ? "set" : ""}"></i>`).join("")}</div><small>64 pixels wide, most-significant bit first. Mark the range as bitmap in the project when this interpretation is correct.</small></details></div>`);
  };
  const persistProject = async (action, detail = "") => {
    if (target) return toast("Extract this archive member before saving disassembly project data.", true);
    project.history = [...(project.history || []), { time: new Date().toISOString(), action, detail }];
    project = await saveEditorProject(pane, path, project);
  };
  const refreshProjectListing = async () => {
    const values = Object.fromEntries(new FormData(modalContent.closest("form")));
    analysisLoading("Applying disassembly project", path);
    await renderDisassemblyEditor(index, entry, path, inspection, values.architecture, values.origin, values.start, values.length, selectedRange()?.start, target);
  };
  const markRegion = async kind => {
    const range = selectedRange();
    if (!range) return toast("Select one or more disassembly lines first.", true);
    const name = await promptValue(`Name this ${kind} region`, "Region name", { value: `${kind}_${range.start.toString(16).toUpperCase()}`, message: `Covers file offsets ${range.start} to ${range.end}.`, confirmLabel: "Mark region", required: false });
    if (name == null) return;
    project.regions = [...(project.regions || []).filter(row => Number(row.end) <= range.start || Number(row.start) >= range.end), { start: range.start, end: range.end, kind, name: name || kind, width: 8 }];
    await persistProject(`Marked ${kind} region`, `${range.start}-${range.end}`);
    await refreshProjectListing();
  };
  const showProjectHistory = () => intelligence?.showCustom("Project history", (project.history || []).length
    ? `<div class="code-history-list">${[...(project.history || [])].reverse().map(item => `<article><time>${esc(item.time || "")}</time><b>${esc(item.action || "Change")}</b><span>${esc(item.detail || "")}</span></article>`).join("")}</div>`
    : '<p class="code-empty-message">No retained project changes exist for this file.</p>');
  const showDisassemblyOutline = () => {
    const labelled = report.rows.filter(row => row.label);
    intelligence?.showCustom("Program outline and call graph", labelled.length ? `<div class="code-outline-list">${labelled.map(row => {
      const callers = report.rows.filter(sourceRow => Number(sourceRow.target) === Number(row.address));
      return `<article><button type="button" data-disassembly-offset="${Number(row.offset)}"><b>${esc(row.label)}</b><span>&amp;${Number(row.address).toString(16).toUpperCase()} · ${callers.length} caller${callers.length === 1 ? "" : "s"}</span></button></article>`;
    }).join("")}</div>` : '<p class="code-empty-message">No labelled entry points were found in this range.</p>');
  };
  root.querySelectorAll("[data-disassembly-action]").forEach(control => control.addEventListener("click", async event => {
    event.preventDefault();
    closeEditorMenus(root);
    const action = control.dataset.disassemblyAction;
    if (action === "close") modal.close();
    else if (action === "save-as") downloadDocument(`${entry.name}.asm`, disassemblyText(report), "text/plain;charset=utf-8");
    else if (action === "export") downloadDocument(`${entry.name}-disassembly.txt`, disassemblyText(report), "text/plain;charset=utf-8");
    else if (action === "select-all") selectSource();
    else if (action === "copy") {
      const selected = window.getSelection()?.toString();
      try { await navigator.clipboard.writeText(selected || disassemblyText(report)); }
      catch (_error) { toast("Clipboard access was refused by the browser. Use Ctrl+C after Select All.", true); }
    } else if (action === "find") findSource();
    else if (action === "find-references") {
      const row = reportRow(selectedLines[0]);
      if (!row) return toast("Select a disassembly line first.", true);
      const matches = report.rows.filter(item => Number(item.target) === Number(row.address) || (item.references || []).map(Number).includes(Number(row.address)));
      intelligence?.showCustom(`References to &${Number(row.address).toString(16).toUpperCase()}`, matches.length ? `<div class="code-reference-results">${matches.map(item => `<button type="button" data-disassembly-offset="${Number(item.offset)}"><b>&amp;${Number(item.address).toString(16).toUpperCase()}</b><code>${esc(`${item.mnemonic} ${item.operand || ""}`)}</code></button>`).join("")}</div>` : '<p class="code-empty-message">No direct references were decoded in this range.</p>');
    }
    else if (action === "rename-symbol") {
      const row = reportRow(selectedLines[0]);
      if (!row) return toast("Select a disassembly line first.", true);
      const name = await promptValue("Rename this symbol", "Symbol name", { value: row.label || `loc_${Number(row.address).toString(16).toUpperCase()}`, message: `The label used for address &${Number(row.address).toString(16).toUpperCase()} throughout the disassembly.`, confirmLabel: "Rename symbol" });
      if (name) { project.symbols = { ...(project.symbols || {}), [String(Number(row.address))]: name }; await persistProject("Renamed symbol", `&${Number(row.address).toString(16).toUpperCase()} = ${name}`); await refreshProjectListing(); }
    }
    else if (action === "fold-toggle-all") intelligence?.toggleAll();
    else if (action === "sync-bytes") { synchronizedBytes = !synchronizedBytes; syncPanel.hidden = !synchronizedBytes; control.querySelector("span").textContent = synchronizedBytes ? "Hide synchronized bytes" : "Show synchronized bytes"; if (synchronizedBytes) await updateDisassemblyBytes(); }
    else if (action === "inspect-data") await inspectSelectedData();
    else if (action === "cheat-candidates") await showEditorCheatCandidates(root, intelligence, pane, path, false, target);
    else if (action === "assemble") {
      if (target) return toast("Extract this archive member before replacing it with assembler output.", true);
      const status = await api(`/api/images/${pane.image.id}/editor-assembler`);
      if (!status.available) return toast(status.message, true);
      const values = await assemblySourceEditor(entry, report);
      if (!values) return;
      analysisLoading("Assembling and validating binary", entry.name);
      try {
        const result = await api(`/api/images/${pane.image.id}/editor-assembler`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path, partition: pane.partition, side: pane.side, source: values.source, architecture: values.architecture, origin: values.origin, sha256: report.sha256 }),
        });
        pane.image = result.image;
        modal.close();
        await loadDirectory(index);
        toast(`Assembler output replaced ${entry.name}: ${result.result.size.toLocaleString()} bytes, ${result.result.changedBytes.toLocaleString()} changed.`);
      } catch (error) { toast(error.message, true); modal.close(); }
    }
    else if (action === "debug") {
      if (target) return toast("Extract this archive member before starting a debugger.", true);
      const row = reportRow(selectedLines[0]);
      await openDebuggerWorkspace(pane, entry, path, report.architecture, `0x${Number(row?.address ?? report.origin).toString(16).toUpperCase()}`);
      project = await loadEditorProject(pane, path);
    }
    else if (action.startsWith("mark-")) await markRegion(action.slice(5));
    else if (action === "bookmark") {
      const range = selectedRange(); if (!range) return toast("Select a disassembly line first.", true);
      const name = await promptValue("Add a bookmark", "Bookmark name", { value: `Offset ${range.start}`, message: `The bookmark points at file offset ${range.start}.`, confirmLabel: "Add bookmark" });
      if (name) {
        const note = await promptValue("Bookmark note", "Note", { message: `An optional note kept with “${name}”.`, confirmLabel: "Add bookmark", required: false, trim: false });
        project.bookmarks = [...(project.bookmarks || []), { offset: range.start, name, note: note || "" }];
        await persistProject("Added bookmark", name); await refreshProjectListing();
      }
    }
    else if (action === "comment") {
      const range = selectedRange(); if (!range) return toast("Select a disassembly line first.", true);
      const key = String(range.start);
      const comment = await promptValue("Comment this line", "Comment", { value: project.comments?.[key] || "", message: `Kept against file offset ${range.start}. Leave it empty to remove the comment.`, confirmLabel: "Save comment", required: false, trim: false });
      if (comment == null) return;
      project.comments = { ...(project.comments || {}) };
      if (comment.trim()) project.comments[key] = comment.trim(); else delete project.comments[key];
      await persistProject(comment.trim() ? "Updated line comment" : "Removed line comment", `Offset ${range.start}`);
      await refreshProjectListing();
    }
    else if (action === "notes") { const notes = await promptValue("Project notes", "Notes", { value: project.notes || "", message: "Notes are stored in the private recoverable session, not in the file bytes.", confirmLabel: "Save notes", required: false, trim: false }); if (notes != null) { project.notes = notes; await persistProject("Updated project notes"); toast("Project notes saved."); } }
    else if (action === "symbols-export") {
      const body = Object.entries(project.symbols || {}).sort((a, b) => Number(a[0]) - Number(b[0])).map(([address, name]) => `&${Number(address).toString(16).toUpperCase()} = ${name}`).join("\n");
      downloadDocument(`${entry.name}.symbols`, body, "text/plain;charset=utf-8");
    }
    else if (action === "symbols-import") {
      const picker = document.createElement("input"); picker.type = "file"; picker.accept = ".symbols,.sym,.txt";
      picker.onchange = async () => { const body = await picker.files[0].text(); const symbols = { ...(project.symbols || {}) }; body.split(/\r?\n/).forEach(line => { const match = line.match(/^\s*(?:&|0x)?([0-9a-f]+)\s*(?:=|\s)\s*([A-Za-z_.][A-Za-z0-9_.]*)/i); if (match) symbols[String(Number.parseInt(match[1], 16))] = match[2]; }); project.symbols = symbols; await persistProject("Imported symbol file", picker.files[0].name); await refreshProjectListing(); }; picker.click();
    }
    else if (action === "outline") showDisassemblyOutline();
    else if (action === "history") showProjectHistory();
    else if (action === "tests") intelligence?.showCustom("Emulator and debugger results", editorTestResultsMarkup(project));
    else if (action === "run-emulator") {
      const result = await runFileInConfiguredEmulator(pane, entry, path, target);
      if (result) { project = result.project; intelligence?.showCustom("Emulator result", editorTestResultsMarkup(project)); }
    }
    else if (action === "hex") openFileHexEditor(index, entry, path, modalContent, 0, target);
    else if (action === "help-overview") intelligence?.overview();
    else if (action === "help-reference") intelligence?.reference();
    else if (action === "help-symbols") intelligence?.showSymbols();
    else if (action === "help-problems") intelligence?.showProblems();
  }));
  const focusLine = offset => {
    const lines = [...root.querySelectorAll(".disassembly-source-line")];
    const line = lines.find(item => Number(item.dataset.offset) === Number(offset))
      || lines.filter(item => Number(item.dataset.offset) <= Number(offset)).at(-1);
    if (!line) return false;
    lines.forEach(item => item.classList.remove("found"));
    line.classList.add("found");
    line.scrollIntoView({ block: "center" });
    line.focus();
    return true;
  };
  root.querySelectorAll("[data-string-offset]").forEach(button => button.onclick = async () => {
    const offset = Number(button.dataset.stringOffset);
    if (offset >= Number(report.start) && offset < Number(report.end) && focusLine(offset)) return;
    analysisLoading("Disassembling string location", `File offset ${offset.toLocaleString()}…`);
    try {
      await renderDisassemblyEditor(
        index, entry, path, inspection, report.architecture,
        `0x${Number(report.origin).toString(16).toUpperCase()}`, String(offset), length, offset, target,
      );
    } catch (error) { toast(error.message, true); modal.close(); }
  });
  root.querySelectorAll(".disassembly-source-line").forEach(line => line.ondblclick = () =>
    openFileHexEditor(index, entry, path, modalContent, Number(line.dataset.offset), target));
  root.addEventListener("keydown", event => {
    if (!(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLocaleLowerCase();
    if (key === "w") { event.preventDefault(); modal.close(); }
    else if (key === "f") { event.preventDefault(); findSource(); }
  });
  if (focusOffset != null) requestAnimationFrame(() => focusLine(focusOffset));
}

async function openFileEditor(index, name, target = null, pathOverride = null, focusOffset = null) {
  const pane = panes[index];
  const entry = pane.entries.find(item => String(item.name).toLocaleLowerCase() === String(name).toLocaleLowerCase());
  if (!entry) return toast("That file is no longer present. Refresh the pane and try again.", true);
  const path = target?.displayPath || pathOverride || entryImagePath(pane, entry);
  if (!target) retainEditorDocument(index, pane, entry, path, "source");
  analysisLoading("Inspecting file", path);
  const query = target ? new URLSearchParams(target.context) : fileContextQuery(pane, path);
  try {
    const report = await api(`${target?.inspectEndpoint || `/api/images/${pane.image.id}/inspect`}?${query}`);
    pane.fileKinds[fileKindKey(pane, entry.name)] = report.view;
    renderPane(index, true);
    if (report.view === "container") {
      if (target) {
        modal.close();
        return openFileHexEditor(index, entry, path, null, 0, target);
      }
      modal.close();
      pane.archivePath = path;
      pane.archiveName = entry.name;
      pane.archiveMember = "";
      return loadDirectory(index);
    }
    // No offset and no length unless the caller is jumping to somewhere
    // specific, so that a program listing opens at its code rather than at
    // its 28-byte header.
    if (report.view === "disassembly") return renderDisassemblyEditor(
      index, entry, path, report, "auto", "",
      focusOffset === null || focusOffset === undefined ? "" : String(focusOffset),
      "", focusOffset, target,
    );
    if (report.view === "hex") {
      modal.close();
      return openFileHexEditor(index, entry, path, null, focusOffset ?? 0, target);
    }
    const canEdit = report.editable && !report.readOnly && !pane.image.readOnly;
    const isBasic = report.view === "basic";
    const isScript = report.view === "script";
    const downloadUrl = target?.downloadUrl || fileDownloadUrl(pane, path);
    const sourceKind = isBasic ? `${esc(report.basic.dialect)} · ${report.basic.lineCount} LINES` : isScript ? `GEMDOS CONFIGURATION FILE · ${report.script.lineCount} LINES` : "TEXT FILE";
    const editorRows = Math.max(7, Math.min(24, report.text.split("\n").length + 1));
    if (!replaceAnalysisLoading(`<div class="analysis-dialog file-inspector source-editor"><header><div><small>${sourceKind} · ${humanSize(report.size)}</small><h2>${esc(entry.name)}</h2></div></header>
      ${editorMenus({ downloadUrl, downloadLabel: target ? "Export original archive member…" : "Download with metadata…", canEdit, canSaveAs: canEdit && !target, canChangeProperties: !target && !pane.image.readOnly && !CONTAINER_KINDS.includes(pane.image.kind), basic: isBasic, readOnly: !canEdit })}
      <textarea class="inspector-content source-content${isBasic ? " basic-source" : ""}" name="inspectedText" rows="${editorRows}" spellcheck="false" wrap="off" ${canEdit ? "" : "readonly"}>${esc(report.text)}</textarea>
      <aside class="source-byte-sync" aria-live="polite" hidden></aside>
      ${report.containerProject ? `<div class="help-note"><strong>Safe container project:</strong> ${esc(report.containerProject.proof)} The edited member must remain exactly ${Number(report.containerProject.length).toLocaleString()} bytes.</div>` : target ? `<div class="help-note">${canEdit ? `${CONTAINER_KINDS.includes(pane.archiveKind) ? "A structural comparison is shown before saving. " : ""}Saving rebuilds the containing archive transactionally and records an image undo checkpoint.` : "This container cannot be rebuilt safely. Exporting keeps the original member bytes."}</div>` : ""}
      ${isBasic && report.basic.editable && report.basic.editNote ? `<div class="help-note">${esc(report.basic.editNote)} Saving replaces only the tokenised program prefix.</div>` : ""}
      ${isBasic && !report.editable ? `<div class="help-warning">${esc(report.basic.dialect)} cannot yet be safely retokenised by this editor${report.basic.trailingBytes ? ` and it also carries ${Number(report.basic.trailingBytes).toLocaleString()} trailing bytes` : ""}. It is open read-only; the raw bytes remain available in Hex.</div>` : ""}
      <footer class="editor-status"><span class="editor-document-state">${canEdit ? "Saved" : "Read-only"}</span><span class="editor-position">Ln 1, Col 1</span><span class="editor-size"></span></footer>
      <button class="editor-save-submit" type="submit" value="save" hidden>Save</button></div>`,
    canEdit ? async form => {
      const replacementRequest = target ? {
        ...target.context,
        text: form.get("inspectedText"),
        sha256: report.sha256,
        archiveSha256: report.archiveSha256,
      } : { path, partition: pane.partition, side: pane.side, text: form.get("inspectedText"), sha256: report.sha256 };
      if (report.containerProject || (target && CONTAINER_KINDS.includes(pane.archiveKind))) {
        const previewEndpoint = report.containerProject
          ? `/api/images/${pane.image.id}/inspect/container-rebuild-preview`
          : `/api/images/${pane.image.id}/archive/rebuild-preview`;
        const proof = await api(previewEndpoint, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(replacementRequest),
        });
        const decision = await containerStructuralReview(proof);
        if (decision !== "save") return false;
      }
      const data = await api(target?.inspectEndpoint || `/api/images/${pane.image.id}/inspect`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(target ? replacementRequest : { ...replacementRequest, basic: isBasic })
      });
      pane.image = data.image;
      await loadDirectory(index);
      report.sha256 = data.inspection.sha256;
      if (data.inspection.archiveSha256) report.archiveSha256 = data.inspection.archiveSha256;
      const editor = modalContent.querySelector(".source-content");
      editor.dataset.savedValue = editor.value;
      editor.dispatchEvent(new Event("input", { bubbles: true }));
      updateSourceEditorStatus(modalContent.querySelector(".source-editor"));
      toast(`${entry.name} updated safely. An undo checkpoint is available.`);
      return false;
    } : null)) return;
    const editor = modalContent.querySelector(".source-content");
    editor.dataset.savedValue = editor.value;
    if (!target) {
      let persistenceTimer = null;
      editor.addEventListener("input", () => {
        clearTimeout(persistenceTimer);
        persistenceTimer = setTimeout(captureActiveEditorDocument, 250);
      });
    }
    const retained = !target ? editorDocuments.get(editorWorkspace.state.active) : null;
    if (retained?.draft != null) {
      editor.value = retained.draft;
      editor.dataset.savedValue = retained.savedValue ?? report.text;
      requestAnimationFrame(() => {
        editor.setSelectionRange(retained.selectionStart || 0, retained.selectionEnd || retained.selectionStart || 0);
        editor.scrollTop = retained.scrollTop || 0;
        editor.scrollLeft = retained.scrollLeft || 0;
        updateSourceEditorStatus(modalContent.querySelector(".source-editor"));
      });
    }
    installEditorWindow(modalContent.querySelector(".source-editor"));
    if (!target) installEditorDocumentTabs(modalContent.querySelector(".source-editor"), pane);
    if (!target) {
      try { report.project = await loadEditorProject(pane, path); }
      catch (_error) { report.project = null; }
    }
    const intelligence = window.AtariCodeEditor?.enhance({
      textarea: editor,
      root: modalContent.querySelector(".source-editor"),
      language: isBasic ? "basic" : isScript ? "script" : "text",
      dialect: report.basic?.dialect || "gfa-basic-3",
      inlineAssemblyLanguage: isBasic && ["tt030", "falcon030"].includes(editorTargetProfile(pane).machine) ? "68030" : "68000",
      targetProfile: editorTargetProfile(pane),
      initialHistory: report.project?.history || [],
      validateBasic: isBasic ? async (text, baseline = "") => api(`/api/images/${pane.image.id}/inspect/basic/verify`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, baseline }),
      }) : null,
      packBasic: isBasic ? async runs => {
        const result = await api(`/api/images/${pane.image.id}/inspect/basic/pack`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ runs }),
        });
        return result.groups;
      } : null,
    });
    installSourceEditorControls(index, pane, entry, path, report, canEdit, isBasic, target, intelligence);
    const renumber = modalContent.querySelector(".basic-renumber");
    if (renumber) renumber.onclick = async () => {
      const editor = modalContent.querySelector(".basic-source");
      renumber.disabled = true;
      renumber.textContent = "Renumbering…";
      try {
        const result = await api(`/api/images/${pane.image.id}/inspect/basic/renumber`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: editor.value, start: modalContent.querySelector('[name="renumberStart"]').value, step: modalContent.querySelector('[name="renumberStep"]').value })
        });
        editor.value = result.text;
        editor.focus();
        editor.dispatchEvent(new Event("input", { bubbles: true }));
        intelligence?.recordHistory?.("Renumbered BASIC", `${result.lineCount} lines`);
        toast(`${result.lineCount} BASIC lines renumbered, including encoded line references. Save to write the program.`);
      } catch (error) { toast(error.message, true); }
      finally { renumber.disabled = false; renumber.textContent = "Renumber"; }
    };
  } catch (error) { toast(error.message, true); modal.close(); }
}

async function showDependencyReport(index) {
  const selected = selectedInspectable(index);
  if (!selected) return toast("Select a launcher file first.", true);
  const { pane, path } = selected;
  analysisLoading("Checking loader dependencies", path);
  const query = new URLSearchParams({ path, ...(pane.partition != null ? { partition: pane.partition } : {}), ...(pane.side != null ? { side: pane.side } : {}) });
  try {
    const report = await trackedPaneOperation(
      index,
      "Checking loader dependencies",
      operationId => {
        query.set("operationId", operationId);
        return api(`/api/images/${pane.image.id}/dependencies?${query}`);
      },
      { abortMode: "read-only" },
    );
    if (!replaceAnalysisLoading(`<div class="analysis-dialog"><small>DEPENDENCY-AWARE COPY CHECK</small><h2>${report.safeForSubdirectory ? "Safe for a subdirectory" : "Review before moving"}</h2>
      <div class="health-checks">${report.dependencies.map(item => `<article class="health-check ${item.resolved && !item.rootRelative ? "pass" : "warn"}"><b>${item.resolved ? "✓" : "!"}</b><span><strong>${esc(item.action)} ${esc(item.target)}</strong><small>${item.resolved ? `Found at ${esc(item.path)}` : "Not found beside launcher"}${item.rootRelative ? " · root-relative" : ""}</small></span></article>`).join("") || "<p>No conventional file dependencies were found.</p>"}</div>
      <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div></div>`)) return;
  } catch (error) { toast(error.message, true); modal.close(); }
}

async function showEditorCheatCandidates(root, intelligence, pane, path, online = false, target = null) {
  intelligence?.showCustom("Cheat candidates", `<div class="analysis-loading compact"><span class="modal-progress-icon">↻</span><p>${online ? "Analysing code and checking online title evidence…" : "Correlating gameplay state, memory writes and control flow…"}</p></div>`);
  dockEditorIntelligence(root);
  const query = new URLSearchParams(target?.context || Object.fromEntries(fileContextQuery(pane, path)));
  query.set("online", String(online));
  try {
    query.set("operationId", newUuid());
    const report = await api(`${target?.cheatEndpoint || `/api/images/${pane.image.id}/cheat-candidates`}?${query}`);
    const categories = [...new Set(report.findings.map(item => item.category))].sort();
    const cards = report.findings.map((item, itemIndex) => `<button type="button" class="cheat-candidate ${esc(item.confidence)}" data-cheat-index="${itemIndex}" data-cheat-category="${esc(item.category)}" data-cheat-confidence="${esc(item.confidence)}" data-cheat-navigation="${esc(JSON.stringify(item.navigation || {}))}" title="Go to this candidate in the code">
      <header><span class="pill">${esc(item.confidence)}</span><b>${esc(item.category)}</b><code>${esc(item.location)}</code></header>
      <strong>${esc(item.summary)}</strong><small>${esc(item.evidence)}</small><p>${esc(item.suggestion)}</p><em>${esc(item.risk)}</em>
    </button>`).join("");
    const matches = report.identificationMatches.map(item => `<li><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a><small>${esc([item.publisher, item.year, item.source].filter(Boolean).join(" · "))}</small></li>`).join("");
    const diagnostics = (report.diagnostics || []).map(item => `<article class="cheat-analysis-diagnostic ${esc(item.kind)}"><strong>${esc(item.title)}</strong><p>${esc(item.detail)}</p></article>`).join("");
    const references = report.referenceSearches.map(item => `<a class="button small" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">Search ${esc(item.name)}</a>`).join("");
    intelligence?.showCustom("Cheat candidates", `<div class="cheat-analysis-dialog">
      <header><div><small>READ-ONLY CODE AND GAME-STATE ANALYSIS</small><strong>${esc(report.title)}</strong></div><span class="health-score ${report.findings.length ? "attention" : "healthy"}">${report.findings.length} found</span></header>
      <p class="help-warning"><strong>Candidate evidence, not a proven cheat.</strong> ${esc(report.warning)}</p>
      <div class="operation-summary"><span><b>${Number(report.counts.strong)}</b><small>Strong</small></span><span><b>${Number(report.counts.likely)}</b><small>Likely</small></span><span><b>${Number(report.counts.possible)}</b><small>Possible</small></span><span><b>${esc(report.kind)}</b><small>Detected code</small></span></div>
      ${diagnostics ? `<div class="cheat-analysis-diagnostics">${diagnostics}</div>` : ""}
      <div class="cheat-analysis-filters"><label>Purpose<select name="cheatCategory"><option value="">All candidate types</option>${categories.map(category => `<option value="${esc(category)}">${esc(category)}</option>`).join("")}</select></label><label>Confidence<select name="cheatConfidence"><option value="">All confidence levels</option><option value="strong">Strong</option><option value="likely">Likely</option><option value="possible">Possible</option></select></label></div>
      <div class="cheat-candidate-list">${cards || `<div class="empty-list">No static candidate was found in this file.${diagnostics ? " The analysis notes above explain the most likely reason." : " Encrypted, compressed, self-modifying or indirectly addressed code needs runtime tracing."}</div>`}</div>
      <details class="cheat-online-evidence" ${matches ? "open" : ""}><summary>Game identification and published references</summary><p>Detected title: <strong>${esc(report.title)}</strong> · target: ${esc(report.machine || "not configured")}</p>${matches ? `<ul>${matches}</ul>` : '<p>No internet identification was requested. The searches below open only when selected.</p>'}<div class="collection-transfer">${references}</div></details>
      <div class="modal-actions"><button class="button ghost" type="button" data-cheat-library>Private cheat library…</button><button class="button primary" type="button" data-cheat-prove disabled>Prepare guarded patch…</button>${online ? "" : '<button class="button ghost" type="button" data-cheat-online>Check online title evidence</button>'}</div>
    </div>`);
    dockEditorIntelligence(root);
    const panel = root.querySelector(".cheat-analysis-dialog");
    if (!panel) return;
    const filter = () => {
      const category = panel.querySelector('[name="cheatCategory"]').value;
      const confidence = panel.querySelector('[name="cheatConfidence"]').value;
      panel.querySelectorAll("[data-cheat-index]").forEach(card => {
        card.hidden = Boolean((category && card.dataset.cheatCategory !== category) || (confidence && card.dataset.cheatConfidence !== confidence));
      });
    };
    panel.querySelector('[name="cheatCategory"]').onchange = filter;
    panel.querySelector('[name="cheatConfidence"]').onchange = filter;
    let selectedFinding = null;
    panel.querySelectorAll("[data-cheat-navigation]").forEach(card => card.addEventListener("click", () => {
      try {
        const navigation = JSON.parse(card.dataset.cheatNavigation);
        focusEditorCheatCandidate(root, navigation);
        panel.querySelectorAll(".cheat-candidate.selected").forEach(item => item.classList.remove("selected"));
        card.classList.add("selected");
        selectedFinding = report.findings[Number(card.dataset.cheatIndex)];
        const prove = panel.querySelector("[data-cheat-prove]");
        prove.disabled = !Number.isInteger(Number(navigation.offset)) || report.kind === "ST BASIC" || Boolean(target?.context?.member);
      }
      catch (_error) { toast("That candidate could not be located in the current editor view.", true); }
    }));
    panel.querySelector("[data-cheat-online]")?.addEventListener("click", () => showEditorCheatCandidates(root, intelligence, pane, path, true, target));
    panel.querySelector("[data-cheat-prove]")?.addEventListener("click", () => showGuardedCheatPatch(root, pane, path, report, selectedFinding, target));
    panel.querySelector("[data-cheat-library]")?.addEventListener("click", () => showCheatLibrary(root, pane, path, target));
  } catch (error) {
    intelligence?.showCustom("Cheat candidates", `<p class="code-empty-message">${esc(error.message)}</p>`);
    dockEditorIntelligence(root);
    toast(error.message, true);
  }
}

const CHEAT_LIBRARY_KEY = "atari-file-forge-cheat-library-v1";

function readCheatLibrary() {
  try {
    const rows = JSON.parse(persistentStorage.getItem(CHEAT_LIBRARY_KEY) || "[]");
    return Array.isArray(rows) ? rows.filter(row => row?.format === "atari-file-forge-cheat-patch" && row?.version === 1).slice(-500) : [];
  } catch (_error) { return []; }
}

function retainCheatPatch(patch) {
  const rows = readCheatLibrary().filter(row => row.id !== patch.id);
  rows.push(patch);
  persistentStorage.setItem(CHEAT_LIBRARY_KEY, JSON.stringify(rows.slice(-500)));
}

async function showGuardedCheatPatch(root, pane, path, report, finding, target = null) {
  if (!finding?.navigation || !Number.isInteger(Number(finding.navigation.offset))) return toast("Select a machine-code candidate with an exact file offset first.", true);
  const context = new URLSearchParams(target?.context || Object.fromEntries(fileContextQuery(pane, path)));
  context.set("offset", String(finding.navigation.offset));
  context.set("length", "1");
  try {
    const source = await api(`/api/images/${pane.image.id}/cheat-patch/context?${context}`);
    const shade = document.createElement("div");
    shade.className = "editor-choice-shade";
    shade.setAttribute("role", "dialog");
    shade.setAttribute("aria-modal", "true");
    shade.innerHTML = `
      <form class="editor-choice-card guarded-cheat-patch-dialog">
        <small>EXACT-HASH PROJECT PATCH</small><h2>Prove and guard a cheat patch</h2>
        <p class="help-warning"><strong>This does not prove a cheat automatically.</strong> Use the configured emulator debugger, set the stated watchpoint, and record at least two distinct gameplay events. Apply remains guarded by the exact file hash and original bytes.</p>
        <div class="operation-summary"><span><b>&amp;${Number(source.offset).toString(16).toUpperCase()}</b><small>File offset</small></span><span><b>${esc(source.originalHex)}</b><small>Current byte</small></span><span><b>${esc(source.sourceSha256.slice(0, 12))}…</b><small>Exact source</small></span></div>
        <div class="guarded-cheat-grid">
          <label>Patch title<input name="title" value="${esc(`${report.title}: ${finding.category}`)}" required></label>
          <label>Author<input name="author" required></label>
          <label>File offset<input name="offset" type="number" min="0" value="${Number(source.offset)}" readonly></label>
          <label>Watchpoint address<input name="watchAddress" value="${esc((finding.evidence.match(/&[0-9A-F]+/i) || [""])[0])}" placeholder="&70" required></label>
          <label>Original bytes<input name="originalHex" value="${esc(source.originalHex)}" pattern="[0-9A-Fa-f ,]+" required><small>Extend this from the disassembly when replacing a multi-byte instruction.</small></label>
          <label>Replacement bytes<input name="replacementHex" placeholder="EA EA" pattern="[0-9A-Fa-f ,]+" required><small>Must contain the same number of bytes.</small></label>
          <label class="wide">Rationale<textarea name="rationale" rows="3" minlength="12" required>${esc(finding.summary)}. ${esc(finding.evidence)}</textarea></label>
          <fieldset><legend>Observation 1</legend><input name="event1" placeholder="Player loses first life" required><input name="before1" placeholder="Before value" required><input name="after1" placeholder="After value" required></fieldset>
          <fieldset><legend>Observation 2</legend><input name="event2" placeholder="Player loses second life" required><input name="before2" placeholder="Before value" required><input name="after2" placeholder="After value" required></fieldset>
        </div>
        <div class="modal-actions"><button class="button ghost" type="button" data-cheat-patch-cancel>Cancel</button><button class="button primary" type="submit">Validate patch</button></div>
      </form>`;
    const formElement = shade.querySelector("form");
    const close = () => { shade.remove(); root?.focus?.(); };
    shade.querySelector("[data-cheat-patch-cancel]").onclick = close;
    shade.onkeydown = event => { if (event.key === "Escape") close(); else trapFocus(shade, event); };
    formElement.onsubmit = async event => {
      event.preventDefault();
      const form = new FormData(formElement);
      const controls = [...formElement.elements];
      controls.forEach(control => { control.disabled = true; });
      formElement.setAttribute("aria-busy", "true");
      try {
        const documentValue = {
          path, partition: pane.partition, side: pane.side, member: target?.context?.member,
          sourceSha256: source.sourceSha256, offset: Number(form.get("offset")),
          originalHex: form.get("originalHex"), replacementHex: form.get("replacementHex"),
          watchAddress: form.get("watchAddress"), title: form.get("title"), author: form.get("author"),
          rationale: form.get("rationale"), hardwareProfile: editorTargetProfile(pane),
          observations: [1, 2].map(number => ({ event: form.get(`event${number}`), before: form.get(`before${number}`), after: form.get(`after${number}`), emulator: report.machine })),
        };
        const preview = await api(`/api/images/${pane.image.id}/cheat-patch/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(documentValue) });
        retainCheatPatch(preview.patch);
        downloadDocument(`${String(report.title || "cheat").replace(/[^A-Za-z0-9_-]+/g, "-")}.affcheat.json`, JSON.stringify(preview.patch, null, 2));
        if (!await confirmChoice("Apply this patch?", `${preview.patch.replacementHex} will be written at file offset &${Number(preview.patch.offset).toString(16).toUpperCase()}.`, { confirmLabel: "Apply patch", danger: true, note: "An automatic image checkpoint is created first." })) return;
        const applied = await api(`/api/images/${pane.image.id}/cheat-patch/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ patch: preview.patch, partition: pane.partition, side: pane.side }) });
        pane.image = applied.image;
        close();
        modal.close();
        renderAll();
        toast("Guarded cheat patch applied. Test it before relying on the result.");
      } catch (error) { toast(error.message, true); }
      finally {
        controls.forEach(control => { control.disabled = false; });
        formElement.removeAttribute("aria-busy");
      }
    };
    modal.append(shade);
    formElement.elements.author.focus();
  } catch (error) { toast(error.message, true); }
}

function showCheatLibrary(root, pane, path, target = null) {
  const rows = readCheatLibrary();
  const shade = document.createElement("div");
  shade.className = "editor-choice-shade";
  shade.setAttribute("role", "dialog");
  shade.setAttribute("aria-modal", "true");
  shade.innerHTML = `
    <section class="editor-choice-card cheat-library-dialog"><small>BROWSER-PRIVATE EXACT-HASH LIBRARY</small><h2>Guarded cheat patches</h2>
      <p>Entries match a complete source SHA-256 and guarded original bytes, never a title alone. Image data is not stored here.</p>
      <div class="cheat-library-list">${rows.map((row, index) => `<article><div><strong>${esc(row.title)}</strong><small>${esc(row.path)} · ${esc(row.hardwareProfile?.name || row.hardwareProfile?.machine || "Unspecified machine")}</small><code>${esc(row.sourceSha256.slice(0, 16))}… · &amp;${Number(row.offset).toString(16).toUpperCase()} ${esc(row.originalHex)} → ${esc(row.replacementHex)}</code></div><span><button class="button small" type="button" data-cheat-apply="${index}">Apply to current file</button><button class="button small ghost" type="button" data-cheat-export="${index}">Export</button></span></article>`).join("") || '<div class="empty-list">No guarded patches have been retained in this browser profile.</div>'}</div>
      <div class="modal-actions"><button class="button danger" type="button" data-cheat-clear ${rows.length ? "" : "disabled"}>Clear library</button><button class="button primary" type="button" data-cheat-library-close>Close</button></div>
    </section>`;
  const close = () => { shade.remove(); root?.focus?.(); };
  shade.querySelector("[data-cheat-library-close]").onclick = close;
  shade.onkeydown = event => { if (event.key === "Escape") close(); else trapFocus(shade, event); };
  shade.querySelectorAll("[data-cheat-export]").forEach(button => button.addEventListener("click", () => {
    const row = rows[Number(button.dataset.cheatExport)];
    downloadDocument(`${String(row.title || "cheat").replace(/[^A-Za-z0-9_-]+/g, "-")}.affcheat.json`, JSON.stringify(row, null, 2));
  }));
  shade.querySelectorAll("[data-cheat-apply]").forEach(button => button.addEventListener("click", async () => {
    const patch = rows[Number(button.dataset.cheatApply)];
    if (!await confirmChoice("Apply this guarded patch?", `“${patch.title}” will be applied to the current file.`, { confirmLabel: "Apply if it matches", danger: true, note: "It is applied only if the file's exact SHA-256 and guarded bytes match." })) return;
    button.disabled = true;
    try {
      const applied = await api(`/api/images/${pane.image.id}/cheat-patch/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ patch, path, partition: pane.partition, side: pane.side, member: target?.context?.member }) });
      pane.image = applied.image;
      close();
      modal.close();
      renderAll();
      toast("Guarded cheat patch applied to the exact matching file revision");
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; }
  }));
  shade.querySelector("[data-cheat-clear]")?.addEventListener("click", async () => {
    if (!await confirmChoice("Clear the cheat library?", "Every guarded patch stored for this browser profile is removed.", { confirmLabel: "Clear library", danger: true, note: "Image files and checkpoints are not affected." })) return;
    persistentStorage.removeItem(CHEAT_LIBRARY_KEY);
    close();
    toast("Private cheat library cleared");
  });
  modal.append(shade);
  shade.querySelector("[data-cheat-library-close]").focus();
}

function focusEditorCheatCandidate(root, navigation) {
  if (navigation?.kind === "disassembly") {
    const lines = [...root.querySelectorAll(".disassembly-source-line")];
    const line = lines.find(item => Number(item.dataset.address) === Number(navigation.address))
      || lines.find(item => Number(item.dataset.offset) === Number(navigation.offset));
    if (!line) throw new Error("Candidate is outside the decoded range");
    lines.forEach(item => item.classList.remove("found"));
    line.classList.add("found");
    line.scrollIntoView({ block: "center", behavior: "smooth" });
    line.focus({ preventScroll: true });
    return;
  }
  if (navigation?.kind === "basic-line") {
    const editor = root.querySelector(".source-content");
    const lines = editor.value.split("\n");
    const lineIndex = lines.findIndex(line => Number(line.match(/^\s*(\d+)/)?.[1]) === Number(navigation.line));
    if (lineIndex < 0) throw new Error("BASIC line is not present");
    const start = lines.slice(0, lineIndex).reduce((total, line) => total + line.length + 1, 0);
    editor.focus();
    editor.setSelectionRange(start, start + lines[lineIndex].length);
    editor.scrollTop = Math.max(0, lineIndex * parseFloat(getComputedStyle(editor).lineHeight || "16") - editor.clientHeight / 2);
    editor.dispatchEvent(new Event("select", { bubbles: true }));
    return;
  }
  throw new Error("Candidate has no editor target");
}

//: The code-intelligence side panel and the class names it is styled by are
//: owned by code-editor.js and styles.css, so the selector strings and the
//: two custom properties below are quoted exactly as those files declare
//: them; only the code in this file reads plainly.
function dockEditorIntelligence(root) {
  const panel = root?.querySelector(".code-intelligence-panel");
  const editorSurface = root?.querySelector(".code-editor-surface, .disassembly-source");
  if (!panel || !editorSurface) return;
  let workspace = root.querySelector(":scope > .code-editor-panel-workspace");
  if (!workspace) {
    workspace = document.createElement("div");
    workspace.className = "code-editor-panel-workspace";
    const splitter = document.createElement("button");
    splitter.type = "button";
    splitter.className = "code-editor-panel-splitter";
    splitter.setAttribute("role", "separator");
    splitter.setAttribute("aria-label", "Resize code and cheat-candidate panels");
    splitter.setAttribute("aria-valuemin", "20");
    splitter.setAttribute("aria-valuemax", "75");
    splitter.setAttribute("aria-valuenow", "40");
    editorSurface.before(workspace);
    workspace.append(editorSurface, splitter, panel);
    installEditorPanelSplitter(workspace, splitter);
  }
  root.classList.add("code-panel-docked-right");
  panel.classList.add("code-intelligence-panel-docked");
  const close = panel.querySelector(".code-panel-close");
  close?.addEventListener("click", () => {
    root.classList.remove("code-panel-docked-right");
    panel.classList.remove("code-intelligence-panel-docked");
  }, { once: true });
}

function installEditorPanelSplitter(workspace, splitter) {
  const narrow = () => matchMedia("(max-width: 900px)").matches;
  const updateOrientation = () => splitter.setAttribute("aria-orientation", narrow() ? "horizontal" : "vertical");
  const resize = event => {
    const bounds = workspace.getBoundingClientRect();
    if (narrow()) {
      const height = Math.max(180, Math.min(bounds.height - 150, bounds.bottom - event.clientY));
      workspace.style.setProperty("--code-panel-height", `${height}px`);
      splitter.setAttribute("aria-valuenow", String(Math.round(height / Math.max(1, bounds.height) * 100)));
    } else {
      const width = Math.max(280, Math.min(bounds.width - 320, bounds.right - event.clientX));
      workspace.style.setProperty("--code-panel-width", `${width}px`);
      splitter.setAttribute("aria-valuenow", String(Math.round(width / Math.max(1, bounds.width) * 100)));
    }
  };
  splitter.addEventListener("pointerdown", event => {
    event.preventDefault();
    updateOrientation();
    splitter.setPointerCapture(event.pointerId);
    workspace.classList.add("resizing");
  });
  splitter.addEventListener("pointermove", event => {
    if (splitter.hasPointerCapture(event.pointerId)) resize(event);
  });
  const finish = event => {
    if (splitter.hasPointerCapture(event.pointerId)) splitter.releasePointerCapture(event.pointerId);
    workspace.classList.remove("resizing");
  };
  splitter.addEventListener("pointerup", finish);
  splitter.addEventListener("pointercancel", finish);
  splitter.addEventListener("keydown", event => {
    updateOrientation();
    const keys = narrow() ? ["ArrowUp", "ArrowDown"] : ["ArrowLeft", "ArrowRight"];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    const bounds = workspace.getBoundingClientRect();
    const panel = workspace.querySelector(".code-intelligence-panel").getBoundingClientRect();
    const delta = (event.key === "ArrowLeft" || event.key === "ArrowUp") ? 24 : -24;
    if (narrow()) {
      const height = Math.max(180, Math.min(bounds.height - 150, panel.height + delta));
      workspace.style.setProperty("--code-panel-height", `${height}px`);
      splitter.setAttribute("aria-valuenow", String(Math.round(height / Math.max(1, bounds.height) * 100)));
    } else {
      const width = Math.max(280, Math.min(bounds.width - 320, panel.width + delta));
      workspace.style.setProperty("--code-panel-width", `${width}px`);
      splitter.setAttribute("aria-valuenow", String(Math.round(width / Math.max(1, bounds.width) * 100)));
    }
  });
  updateOrientation();
}

async function showDuplicateReport(index) {
  const pane = panes[index];
  analysisLoading("Finding duplicates and variants", "Hashing directories and comparing normalised titles…");
  try {
    const report = await trackedPaneOperation(
      index,
      "Finding duplicates and variants",
      operationId => api(
        `/api/images/${pane.image.id}/duplicates?${new URLSearchParams({ operationId })}`
      ),
      { abortMode: "read-only" },
    );
    const group = (items, exact) => `<article><strong>${exact ? "Byte-identical" : "Likely variants"} · ${items.length}</strong><small>${items.map(item => item.device ? `${item.device}: ${item.path}` : item.path).map(esc).join("<br>")}</small></article>`;
    if (!replaceAnalysisLoading(`<div class="analysis-dialog wide-analysis"><small>DUPLICATE / VARIANT FINDER</small><h2>${report.exact.length} exact groups · ${report.variants.length} variant groups</h2>
      <div class="duplicate-groups">${report.exact.map(items => group(items, true)).join("")}${report.variants.map(items => group(items, false)).join("") || "<p>No likely variants were found.</p>"}</div>
      <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div></div>`)) return;
  } catch (error) { toast(error.message, true); modal.close(); }
}

function showManifestExport(index) {
  const pane = panes[index];
  showModal(`<h2>Export collection manifest</h2><p>Create a searchable catalogue of partitions, files, GEMDOS attributes, datestamps and checksums.</p>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button" type="button" data-manifest="csv">Download CSV</button><button class="button primary" type="button" data-manifest="json">Download JSON</button></div>`);
  modalContent.querySelectorAll("[data-manifest]").forEach(button => button.onclick = async () => {
    const buttons = [...modalContent.querySelectorAll("[data-manifest]")];
    buttons.forEach(control => { control.disabled = true; });
    modal.classList.add("busy");
    try {
      const response = await trackedPaneOperation(
        index,
        "Building collection manifest",
        operationId => fetch(
          `/api/images/${pane.image.id}/manifest?${new URLSearchParams({
            format: button.dataset.manifest,
            operationId,
          })}`
        ),
        { abortMode: "read-only" },
      );
      const download = await downloadResponse(
        response,
        `${pathNameWithoutExtension(pane.image.name)}-manifest.${button.dataset.manifest}`,
      );
      toast(`Collection manifest ready · ${humanSize(download.size)}`);
      modal.close();
    } catch (error) {
      toast(error.message, true);
    } finally {
      buttons.forEach(control => { control.disabled = false; });
      modal.classList.remove("busy");
    }
  });
}

function comparisonRecordLabel(change) {
  const row = change.after || change.before || {};
  if (row.recordType === "partition") return `${row.device || `Partition ${row.partition}`}`;
  const context = row.partition != null ? `${row.device || `Partition ${row.partition}`} · ` : row.bank != null ? `Bank ${row.bank} · ` : "";
  return `${context}${row.path || change.key}`;
}

function downloadJson(documentValue, filename) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(documentValue, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function fetchCollectionManifest(index) {
  const pane = panes[index];
  const presentingProgress = modal.open;
  if (presentingProgress) modal.classList.add("busy");
  try {
    const response = await trackedPaneOperation(
      index,
      "Indexing image for the private collection",
      operationId => fetch(`/api/images/${pane.image.id}/manifest?${new URLSearchParams({ format: "json", operationId })}`),
      { abortMode: "read-only" },
    );
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || `Collection indexing failed (${response.status})`);
    }
    return response.json();
  } finally {
    if (presentingProgress) modal.classList.remove("busy");
  }
}

function collectionEntryMatchesPane(entry, pane) {
  return entry.sessionId === pane.image.id || (entry.name === pane.image.name && entry.kind === pane.image.kind);
}

async function indexPaneInCollection(index, entries, options = {}) {
  const pane = panes[index];
  const previous = entries.find(entry => entry.id === options.id) || entries.find(entry => collectionEntryMatchesPane(entry, pane));
  const manifest = await fetchCollectionManifest(index);
  const profile = pane.image.hardwareProfile || {};
  return collectionCatalogue.upsertManifest(manifest, {
    id: previous?.id,
    sessionId: pane.image.id,
    location: options.location ?? previous?.location ?? "",
    notes: options.notes ?? previous?.notes ?? "",
    machines: options.machines || previous?.machines || [profile.name || profile.machine || pane.image.targetHardware].filter(Boolean),
  });
}

async function showCollectionCatalogue(initialIndex = null) {
  if (!collectionCatalogue.available) {
    return toast("This browser does not provide IndexedDB, so its private collection cannot be opened.", true);
  }
  try {
    const entries = (await collectionCatalogue.list()).sort((left, right) => left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" }));
    const preferences = await collectionCatalogue.settings();
    const report = window.AtariCollectionCatalogue.collectionReport(entries, preferences.wanted);
    const openPanes = panes.map((pane, index) => ({ pane, index })).filter(item => item.pane.image);
    const selectedIndex = openPanes.some(item => item.index === initialIndex) ? initialIndex : openPanes[0]?.index;
    const selectedPane = panes[selectedIndex];
    const selectedEntry = selectedPane ? entries.find(entry => collectionEntryMatchesPane(entry, selectedPane)) : null;
    const paneOptions = openPanes.map(({ pane, index }) => `<option value="${index}" ${index === selectedIndex ? "selected" : ""}>Pane ${index + 1} · ${esc(pane.image.name)}</option>`).join("");
    const duplicateSummary = report.exactDuplicates.slice(0, 200).map(group => `<li><code>${esc(group[0].sha256.slice(0, 12))}…</code> ${group.map(item => `${esc(item.image)} · ${esc(item.title)}`).join(" / ")}</li>`).join("");
    const variantSummary = report.titleVariants.slice(0, 200).map(group => `<li><b>${esc(group[0].title)}</b> ${group.map(item => esc(item.image)).join(" / ")}</li>`).join("");
    const rows = entries.map(entry => `<tr data-collection-id="${esc(entry.id)}"><td><input type="checkbox" name="collectionImage" value="${esc(entry.id)}" aria-label="Select ${esc(entry.name)}"></td><td><strong>${esc(entry.name)}</strong><small>${esc(entry.location || "No user-supplied location")}</small></td><td>${esc(entry.kind.toUpperCase())}</td><td>${esc(entry.machines.join(", ") || "Not specified")}</td><td>${(entry.records || []).length.toLocaleString()}</td><td><span class="pill ${entry.stale ? "collection-stale" : ""}">${entry.stale ? "Refresh needed" : "Current"}</span><small>${esc(new Date(entry.indexedAt).toLocaleString())}</small></td></tr>`).join("");
    showModal(`<div class="collection-dialog wide-analysis">
      <header><div><small>BROWSER-PRIVATE INDEXEDDB CATALOGUE</small><h2>My Atari collection</h2></div><div class="collection-totals"><b>${report.images}</b> images <b>${report.records.toLocaleString()}</b> records <b>${report.titles}</b> titles</div></header>
      <p>This catalogue belongs only to this browser profile. It stores manifests and user-supplied locations, never image bytes.</p>
      <label class="collection-search">Search saved names, paths, titles, publishers, machines or SHA-256<input type="search" name="collectionQuery" placeholder="Search the complete private catalogue"></label>
      <section class="collection-index-controls"><label>Open image<select name="collectionPane" ${paneOptions ? "" : "disabled"}>${paneOptions || '<option>No open images</option>'}</select></label><label>Location or shelf<input name="collectionLocation" value="${esc(selectedEntry?.location || "")}" placeholder="SD card, NAS path, archive box…"></label><label>Machines<input name="collectionMachines" value="${esc((selectedEntry?.machines || []).join(", "))}" placeholder="Atari STE, Atari Falcon030…"></label><button class="button primary" type="button" data-index-pane ${paneOptions ? "" : "disabled"}>Add / update image</button><button class="button" type="button" data-refresh-open ${entries.length && paneOptions ? "" : "disabled"}>Refresh indexed open images</button></section>
      <div class="collection-list"><table><thead><tr><th></th><th>Image and location</th><th>Format</th><th>Machines</th><th>Records</th><th>Status</th></tr></thead><tbody>${rows || '<tr><td colspan="6">No images have been indexed yet.</td></tr>'}</tbody></table></div>
      <div class="collection-reports"><details><summary>Exact content duplicates (${report.exactDuplicates.length})</summary><ul>${duplicateSummary || "<li>No cross-image duplicate content found.</li>"}</ul></details><details><summary>Title variants (${report.titleVariants.length})</summary><ul>${variantSummary || "<li>No repeated titles found across images.</li>"}</ul></details><details><summary>Wanted and missing titles (${report.missingTitles.length})</summary><label>One wanted title per line<textarea name="wantedTitles" rows="4">${esc((preferences.wanted || []).join("\n"))}</textarea></label><ul>${report.missingTitles.map(title => `<li>${esc(title)}</li>`).join("") || "<li>Every listed title is present.</li>"}</ul><button class="button small" type="button" data-save-wanted>Save wanted list</button></details></div>
      <div class="collection-transfer"><button class="button" type="button" data-export-collection-report>Export report</button><button class="button" type="button" data-backup-collection>Back up database</button><label class="button">Import backup<input type="file" accept="application/json,.json" data-import-collection hidden></label><button class="button danger" type="button" data-remove-collection disabled>Remove selected</button><button class="button danger" type="button" data-clear-collection ${entries.length ? "" : "disabled"}>Clear catalogue</button></div>
      <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div>
    </div>`, null, { replace: modal.open });
    const paneSelect = modalContent.querySelector('[name="collectionPane"]');
    const locationInput = modalContent.querySelector('[name="collectionLocation"]');
    const machinesInput = modalContent.querySelector('[name="collectionMachines"]');
    const selectedIds = () => [...modalContent.querySelectorAll('[name="collectionImage"]:checked')].map(input => input.value);
    modalContent.querySelector('[name="collectionQuery"]').oninput = event => {
      const query = event.target.value.trim().toLocaleLowerCase();
      entries.forEach(entry => {
        const searchable = [entry.name, entry.kind, entry.location, entry.notes, ...(entry.machines || []),
          ...(entry.titles || []).flatMap(title => [title.title, title.publisher]),
          ...(entry.records || []).flatMap(record => [record.path, record.diskTitle, record.title, record.sha256])]
          .filter(Boolean).join(" ").toLocaleLowerCase();
        modalContent.querySelector(`[data-collection-id="${CSS.escape(entry.id)}"]`)?.toggleAttribute("hidden", Boolean(query && !searchable.includes(query)));
      });
    };
    modalContent.querySelectorAll('[name="collectionImage"]').forEach(input => input.onchange = () => { modalContent.querySelector("[data-remove-collection]").disabled = !selectedIds().length; });
    paneSelect?.addEventListener("change", () => {
      const pane = panes[Number(paneSelect.value)];
      const previous = entries.find(entry => collectionEntryMatchesPane(entry, pane));
      locationInput.value = previous?.location || "";
      machinesInput.value = (previous?.machines || []).join(", ");
    });
    modalContent.querySelector("[data-index-pane]")?.addEventListener("click", async event => {
      event.currentTarget.disabled = true;
      try {
        const index = Number(paneSelect.value);
        await indexPaneInCollection(index, entries, { location: locationInput.value.trim(), machines: machinesInput.value.split(",").map(value => value.trim()).filter(Boolean) });
        toast(`${panes[index].image.name} added to the private collection.`);
        await showCollectionCatalogue(index);
      } catch (error) { event.currentTarget.disabled = false; toast(error.message, true); }
    });
    modalContent.querySelector("[data-refresh-open]")?.addEventListener("click", async event => {
      event.currentTarget.disabled = true;
      let refreshed = 0;
      try {
        for (const { pane, index } of openPanes) {
          if (!entries.some(entry => collectionEntryMatchesPane(entry, pane))) continue;
          await indexPaneInCollection(index, entries);
          refreshed += 1;
        }
        toast(`${refreshed} open collection image${refreshed === 1 ? "" : "s"} refreshed.`);
        await showCollectionCatalogue(initialIndex);
      } catch (error) { event.currentTarget.disabled = false; toast(error.message, true); }
    });
    modalContent.querySelector("[data-save-wanted]").onclick = async () => {
      await collectionCatalogue.saveSettings({ wanted: modalContent.querySelector('[name="wantedTitles"]').value.split(/\r?\n/) });
      await showCollectionCatalogue(initialIndex);
    };
    modalContent.querySelector("[data-export-collection-report]").onclick = () => downloadJson({ format: "atari-file-forge-collection-report", version: 1, generatedAt: new Date().toISOString(), ...report }, "atari-file-forge-collection-report.json");
    modalContent.querySelector("[data-backup-collection]").onclick = async () => downloadJson(await collectionCatalogue.exportBackup(), `atari-file-forge-collection-backup-${new Date().toISOString().replace(/[:.]/g, "-")}.json`);
    modalContent.querySelector("[data-import-collection]").onchange = async event => {
      const file = event.target.files[0];
      if (!file || file.size > 128 * 1024 * 1024) return toast("Collection backups are limited to 128 MiB.", true);
      try {
        const document = JSON.parse(await file.text());
        const choice = await overlayDialog(`<section class="editor-choice-card overlay-dialog">
            <h2 id="overlay-dialog-title">Import this backup</h2>
            <p>${esc(file.name)} can replace what this browser holds, or be merged into it.</p>
            <div class="help-note">Merging keeps every record already here and adds the ones the backup carries. Replacing discards them first. Image files are not affected either way.</div>
            <div class="modal-actions">
              <button type="button" class="button ghost" data-choice="cancel">Cancel</button>
              <button type="button" class="button danger" data-choice="replace">Replace catalogue</button>
              <button type="button" class="button primary" data-choice="merge">Merge into catalogue</button>
            </div></section>`);
        if (!choice || choice === "cancel") return;
        const count = await collectionCatalogue.importBackup(document, choice === "replace");
        toast(`${count} collection image${count === 1 ? "" : "s"} imported.`);
        await showCollectionCatalogue(initialIndex);
      } catch (error) { toast(error.message, true); }
    };
    modalContent.querySelector("[data-remove-collection]").onclick = async () => {
      const ids = selectedIds();
      if (!ids.length || !await confirmChoice("Remove the selected records?", `${ids.length} collection record${ids.length === 1 ? "" : "s"} will be removed.`, { confirmLabel: `Remove ${ids.length} record${ids.length === 1 ? "" : "s"}`, danger: true, note: "Image files are not affected." })) return;
      await collectionCatalogue.remove(ids);
      await showCollectionCatalogue(initialIndex);
    };
    modalContent.querySelector("[data-clear-collection]").onclick = async () => {
      if (!await confirmChoice("Clear the whole catalogue?", "Every record in this browser's private collection catalogue is removed.", { confirmLabel: "Clear catalogue", danger: true, note: "Image files are not affected." })) return;
      await collectionCatalogue.clear();
      await showCollectionCatalogue(initialIndex);
    };
  } catch (error) {
    toast(`Could not open the private collection: ${error.message}`, true);
  }
}

async function downloadResponse(response, fallbackFilename) {
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || `Download preparation failed (${response.status})`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || fallbackFilename;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return { filename, size: blob.size };
}

function showImageComparison(index) {
  const pane = panes[index];
  const candidates = panes
    .map((other, otherIndex) => ({ pane: other, index: otherIndex }))
    .filter(item => item.index !== index && item.pane.image?.id && item.pane.image.id !== pane.image.id);
  if (!candidates.length) return toast("Open another image before comparing.", true);
  showModal(`<div class="analysis-dialog wide-analysis image-comparison-dialog">
    <header><div><small>FILESYSTEM-AWARE IMAGE COMPARISON</small><h2>Compare ${esc(pane.image.name)}</h2></div></header>
    <label>Compare against<select name="otherImage">${candidates.map(item => `<option value="${esc(item.pane.image.id)}">Pane ${item.index + 1} · ${esc(item.pane.image.name)} · ${esc(paneFormat(item.pane.image))}</option>`).join("")}</select></label>
    <p class="help-note">Files, folders, partitions and ROM banks are matched by logical location. Content checksums and GEMDOS metadata are separated, then bounded raw-byte ranges are reported for each physical image component.</p>
    <div class="image-comparison-results" aria-live="polite"><p>Choose an image and run the comparison.</p></div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Close</button><button class="button" type="button" data-export-comparison disabled>Export JSON</button><button class="button" type="button" data-export-patch disabled>Download patch</button><button class="button primary" type="button" data-run-comparison>Compare images</button></div>
  </div>`);
  let report = null;
  const resultHost = modalContent.querySelector(".image-comparison-results");
  modalContent.querySelector("[data-run-comparison]").onclick = async event => {
    const button = event.currentTarget;
    button.disabled = true;
    resultHost.innerHTML = "<p>Building manifests and comparing image contents…</p>";
    modal.classList.add("busy");
    try {
      report = await trackedPaneOperation(index, "Comparing image contents", operationId => api(`/api/images/${pane.image.id}/compare`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ otherImage: modalContent.querySelector('[name="otherImage"]').value, operationId }),
      }), { abortMode: "read-only" });
      modalContent.querySelector(".image-comparison-dialog")?.classList.add("comparison-complete");
      const sections = ["added", "removed", "renamed", "modified", "metadata"];
      const patchable = change => {
        const row = change.after || change.before || {};
        if (!report.sameFormat || CONTAINER_KINDS.includes(report.base.kind)) return false;
        if (report.base.kind === "hd") return row.recordType !== "partition";
        if (report.base.kind === "rom") return row.recordType === "rom-bank";
        return true;
      };
      const rawComponents = report.raw?.components || [];
      const rawMarkup = `<details class="raw-comparison" ${report.summary.total < 40 ? "open" : ""}><summary>Raw image evidence · ${Number(report.raw?.changedBytes || 0).toLocaleString()} changed byte${Number(report.raw?.changedBytes) === 1 ? "" : "s"}</summary>${rawComponents.map(component => `<section><b>Primary image</b><small>${Number(component.count).toLocaleString()} changed bytes · ${humanSize(component.sourceSize)} → ${humanSize(component.candidateSize)}${component.truncated ? " · comparison bounded at 1 GiB" : ""}</small>${component.ranges.slice(0, 100).map(range => `<code>+&amp;${Number(range[0]).toString(16).toUpperCase()} to +&amp;${Number(range[1]).toString(16).toUpperCase()} · ${(Number(range[1]) - Number(range[0]) + 1).toLocaleString()} bytes</code>`).join("") || "<em>Byte-identical</em>"}${component.rangesTruncated ? "<em>Additional ranges are retained only in the changed-byte total.</em>" : ""}</section>`).join("") || "<p>No comparable local image components were available.</p>"}</details>`;
      resultHost.innerHTML = `<div class="comparison-summary">${sections.map(name => `<strong><span>${report.summary[name].toLocaleString()}</span>${name}</strong>`).join("")}<strong><span>${report.summary.total.toLocaleString()}</span>total</strong></div>
        ${report.sameFormat ? "" : '<p class="help-warning">These images use different filesystem families. The report is useful for inventory comparison but cannot become a directly applicable patch.</p>'}
        <div class="comparison-change-list">${sections.map(name => report.changes[name].length ? `<details ${report.summary.total < 40 ? "open" : ""}><summary>${name[0].toUpperCase() + name.slice(1)} (${report.changes[name].length})</summary>${report.changes[name].slice(0, 1000).map(change => `<div>${patchable(change) ? `<input type="checkbox" data-patch-key="${esc(change.key)}" aria-label="Include ${esc(comparisonRecordLabel(change))} in a selective patch">` : '<span class="patch-choice-placeholder" aria-hidden="true"></span>'}<b>${esc(comparisonRecordLabel(change))}</b><small>${change.changedFields?.length ? esc(change.changedFields.join(", ")) : name}</small></div>`).join("")}${report.changes[name].length > 1000 ? `<p>${(report.changes[name].length - 1000).toLocaleString()} more changes are included in the JSON export.</p>` : ""}</details>` : "").join("") || '<p class="help-note">The logical contents and metadata are identical.</p>'}${rawMarkup}</div>
        ${report.sameFormat && !CONTAINER_KINDS.includes(report.base.kind) ? '<p class="help-note patch-selection-note">Download patch includes every change. Tick reviewed items to build a dependency-closed selective patch instead.</p>' : ""}`;
      modalContent.querySelector("[data-export-comparison]").disabled = false;
      modalContent.querySelector("[data-export-patch]").disabled = !report.sameFormat || CONTAINER_KINDS.includes(report.base.kind);
      resultHost.querySelectorAll("[data-patch-key]").forEach(input => input.onchange = () => {
        const count = resultHost.querySelectorAll("[data-patch-key]:checked").length;
        modalContent.querySelector("[data-export-patch]").textContent = count ? `Download selected patch (${count})` : "Download patch";
        resultHost.querySelector(".patch-selection-note").textContent = count
          ? `${count} reviewed change${count === 1 ? "" : "s"} selected. Required parent directories or child removals will be included automatically and listed in preflight.`
          : "Download patch includes every change. Tick reviewed items to build a dependency-closed selective patch instead.";
      });
    } catch (error) {
      resultHost.innerHTML = `<p class="help-warning">${esc(error.message)}</p>`;
    } finally { button.disabled = false; modal.classList.remove("busy"); }
  };
  modalContent.querySelector("[data-export-comparison]").onclick = () => {
    if (!report) return;
    downloadJson(report, `${pathNameWithoutExtension(pane.image.name)}-comparison.json`);
  };
  modalContent.querySelector("[data-export-patch]").onclick = event => downloadImagePatch(
    index, pane, modalContent.querySelector('[name="otherImage"]').value, event.currentTarget,
    [...resultHost.querySelectorAll("[data-patch-key]:checked")].map(input => input.dataset.patchKey),
  );
}

async function downloadImagePatch(index, pane, candidateId, button, selectedKeys = []) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Building patch…";
  modal.classList.add("busy");
  try {
    const response = await trackedPaneOperation(index, "Building guarded patch", operationId => (
      selectedKeys.length
        ? fetch(`/api/images/${pane.image.id}/patch/build`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ otherImage: candidateId, operationId, selectedKeys }),
          })
        : fetch(`/api/images/${pane.image.id}/patch?${new URLSearchParams({ otherImage: candidateId, operationId })}`)
    ), { abortMode: "read-only" });
    const download = await downloadResponse(
      response,
      `${pathNameWithoutExtension(pane.image.name)}.affpatch.zip`,
    );
    toast(`Guarded patch ready · ${humanSize(download.size)}`);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = original; modal.classList.remove("busy"); }
}

function showApplyImagePatch(index) {
  const pane = panes[index];
  showModal(`<div class="analysis-dialog patch-preflight-dialog">
    <small>EXACT-REVISION PATCH</small><h2>Apply patch to ${esc(pane.image.name)}</h2>
    <p>Select an <code>.affpatch.zip</code> to inspect. Nothing is written until its format, physical layout, exact base fingerprint and every embedded payload have passed verification.</p>
    <label class="field"><span>Patch archive</span><input type="file" name="patch" accept=".zip,.affpatch.zip,application/zip" required></label>
    <div class="patch-preflight-results" aria-live="polite"><p class="help-note">Choose a patch to see its source, candidate and complete operation summary.</p></div>
    <div class="help-warning"><strong>This changes image contents.</strong> An automatic undo checkpoint is created first. A stale, corrupt or wrong-format patch is rejected and rolled back.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="apply" data-apply-patch disabled>Apply verified patch</button></div>
  </div>`, async form => {
    const data = await trackedPaneOperation(index, "Applying guarded patch", operationId => {
      form.set("operationId", operationId);
      return api(`/api/images/${pane.image.id}/patch`, { method: "POST", body: form });
    }, { abortMode: "atomic" });
    pane.image = data.image;
    await refreshCurrentView(index);
    toast(`${data.patch.operations.toLocaleString()} guarded patch operation${data.patch.operations === 1 ? "" : "s"} applied`);
  });
  const input = modalContent.querySelector('[name="patch"]');
  const applyButton = modalContent.querySelector("[data-apply-patch]");
  const resultHost = modalContent.querySelector(".patch-preflight-results");
  input.onchange = async () => {
    const file = input.files?.[0];
    applyButton.disabled = true;
    if (!file) {
      resultHost.innerHTML = '<p class="help-note">Choose a patch to see its source, candidate and complete operation summary.</p>';
      return;
    }
    resultHost.innerHTML = `<div class="analysis-loading compact"><span class="modal-progress-icon" aria-hidden="true">↻</span><p>Verifying ${esc(file.name)}…</p></div>`;
    const form = new FormData();
    form.append("patch", file, file.name);
    modal.classList.add("busy");
    try {
      const data = await trackedPaneOperation(index, "Verifying guarded patch", operationId => {
        form.set("operationId", operationId);
        return api(`/api/images/${pane.image.id}/patch/inspect`, { method: "POST", body: form });
      }, { abortMode: "read-only" });
      if (input.files?.[0] !== file) return;
      const report = data.patch;
      const summary = report.summary || {};
      const categories = ["added", "removed", "renamed", "modified", "metadata"];
      resultHost.innerHTML = `<div class="patch-preflight-heading"><span><small>BASE</small><b>${esc(report.base?.name || "Unnamed image")}</b></span><i aria-hidden="true">→</i><span><small>CANDIDATE</small><b>${esc(report.candidate?.name || "Unnamed image")}</b></span></div>
        <div class="comparison-summary">${categories.map(name => `<strong><span>${Number(summary[name] || 0).toLocaleString()}</span>${name}</strong>`).join("")}<strong><span>${Number(report.operationCount || 0).toLocaleString()}</span>operations</strong></div>
        <p class="patch-payload-summary">${Number(report.payloadCount || 0).toLocaleString()} verified payload${Number(report.payloadCount) === 1 ? "" : "s"} · ${humanSize(Number(report.payloadBytes || 0))}</p>
        ${report.selection ? `<p class="help-note">Selective patch · ${report.selection.requestedKeys.length.toLocaleString()} reviewed change${report.selection.requestedKeys.length === 1 ? "" : "s"}${report.selection.automaticallyIncludedKeys.length ? ` · ${report.selection.automaticallyIncludedKeys.length.toLocaleString()} structural dependenc${report.selection.automaticallyIncludedKeys.length === 1 ? "y" : "ies"} included automatically` : ""}</p>` : ""}
        <div class="patch-operation-preview">${report.operations.map(operation => `<div><b>${esc(comparisonRecordLabel(operation))}</b><small>${esc(operation.action)}${operation.changedFields?.length ? ` · ${esc(operation.changedFields.join(", "))}` : ""}</small></div>`).join("") || '<p class="code-empty-message">This patch contains no logical changes.</p>'}${report.truncated ? '<p class="help-note">Only the first 200 operations are shown. Every operation and payload was still verified.</p>' : ""}</div>`;
      applyButton.disabled = false;
    } catch (error) {
      if (input.files?.[0] !== file) return;
      resultHost.innerHTML = `<p class="help-warning"><strong>Patch verification failed.</strong> ${esc(error.message)}</p>`;
    } finally { modal.classList.remove("busy"); }
  };
}

async function openWorkspaceSearchResult(result) {
  const pane = panes[result.paneIndex];
  if (!pane?.image) return toast("That image is no longer open.", true);
  paneWindowManager.restore(result.paneIndex);
  paneWindowManager.bringToFront(result.paneIndex);
  if (result.romProject) {
    modal.close();
    return showRomWorkbench(result.paneIndex, {
      tab: result.romTab || "project",
      address: result.address,
      bank: result.bank,
    });
  }
  pane.archivePath = null;
  pane.archiveMember = "";
  if (result.partition != null) pane.partition = Number(result.partition);
  if (result.side != null) pane.side = Number(result.side);
  pane.path = parentPath(result.path);
  modal.close();
  await loadDirectory(result.paneIndex);
  if (result.virtual && !result.openable) return;
  const offsetMatch = result.matches?.find(match => match.offset != null);
  await openFileEditor(
    result.paneIndex, result.fileName || result.name, null, result.path, offsetMatch?.offset ?? null,
  );
}

function showWorkspaceSearch() {
  const searchable = panes
    .map((pane, index) => ({ pane, index }))
    .filter(item => item.pane.image)
    .filter((item, position, all) => all.findIndex(candidate => candidate.pane.image.id === item.pane.image.id) === position);
  if (!searchable.length) return toast("Open an image before searching the workspace.", true);
  showModal(`<div class="analysis-dialog wide-analysis workspace-search-dialog">
    <header><div><small>ALL OPEN IMAGES</small><h2>Search workspace</h2></div></header>
    <div class="workspace-search-controls"><input type="search" name="workspaceQuery" placeholder="Name, metadata, SHA-256 or readable text" required autocomplete="off" autofocus><button class="button primary" type="button" data-run-workspace-search>Search ${searchable.length} image${searchable.length === 1 ? "" : "s"}</button></div>
    <p class="workspace-search-status" aria-live="polite">Searches directories and bounded file content in each distinct open filesystem, including every partition of an open hard drive. Enter an 8 to 64 digit SHA-256 prefix to identify exact content.</p>
    <div class="editor-image-search-results workspace-search-results"></div>
    <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div>
  </div>`);
  const input = modalContent.querySelector('[name="workspaceQuery"]');
  const status = modalContent.querySelector(".workspace-search-status");
  const results = modalContent.querySelector(".workspace-search-results");
  const run = async () => {
    const query = input.value.trim();
    if (!query) return input.focus();
    const button = modalContent.querySelector("[data-run-workspace-search]");
    button.disabled = true;
    status.textContent = `Searching ${searchable.length} open image${searchable.length === 1 ? "" : "s"}…`;
    results.replaceChildren();
    const reports = await Promise.all(searchable.map(async item => {
      const parameters = new URLSearchParams({ query, root: "" });
      if (item.pane.image.kind === "hd") parameters.set("allPartitions", "true");
      try {
        const report = await trackedPaneOperation(
          item.index,
          "Searching image directories and file content",
          operationId => {
            parameters.set("operationId", operationId);
            return api(`/api/images/${item.pane.image.id}/inspect/search?${parameters}`);
          },
          { abortMode: "read-only" },
        );
        return { ...item, report };
      } catch (error) { return { ...item, error }; }
    }));
    const matches = reports.flatMap(item => (item.report?.results || []).map(row => ({ ...row, paneIndex: item.index, imageName: item.pane.image.name })));
    const filesScanned = reports.reduce((total, item) => total + Number(item.report?.filesScanned || 0), 0);
    const skipped = reports.filter(item => item.error);
    modalContent.querySelector(".workspace-search-dialog")?.classList.add("search-complete");
    status.textContent = `${matches.length.toLocaleString()} result${matches.length === 1 ? "" : "s"} · ${filesScanned.toLocaleString()} readable files scanned across ${reports.length - skipped.length} image${reports.length - skipped.length === 1 ? "" : "s"}${skipped.length ? ` · ${skipped.length} unsupported or unreadable image${skipped.length === 1 ? "" : "s"} skipped` : ""}`;
    results.innerHTML = matches.map((row, resultIndex) => {
      const reasons = [
        row.nameMatch ? "Filename" : "",
        ...(row.metadataMatches || []).map(label => `${label} metadata`),
        row.hashMatch ? "SHA-256" : "",
        row.matches?.length ? `${row.matches.length} content match${row.matches.length === 1 ? "" : "es"}` : "",
      ].filter(Boolean);
      return `<button type="button" data-workspace-result="${resultIndex}"><span class="file-kind-icon ${esc(row.kind)}" aria-hidden="true"></span><b><em>Pane ${row.paneIndex + 1} · ${esc(row.imageName)}${row.device ? ` · ${esc(row.device)}:` : ""}</em>${esc(row.path)}</b><small>${esc(reasons.join(" · "))} · ${humanSize(row.size)}</small>${row.hashMatch ? `<code>SHA-256 ${esc(row.sha256)}</code>` : ""}${row.matches.slice(0, 3).map(match => `<code>${match.offset != null ? `Offset &amp;${Number(match.offset).toString(16).toUpperCase()}` : `Line ${match.line}`}: ${esc(match.text)}</code>`).join("")}</button>`;
    }).join("") || '<p class="code-empty-message">No matching files were found.</p>';
    results.querySelectorAll("[data-workspace-result]").forEach(resultButton => resultButton.onclick = () => openWorkspaceSearchResult(matches[Number(resultButton.dataset.workspaceResult)]));
    button.disabled = false;
  };
  modalContent.querySelector("[data-run-workspace-search]").onclick = run;
  input.onkeydown = event => { if (event.key === "Enter") { event.preventDefault(); run(); } };
}

async function showJobsPanel() {
  showModal(`<div class="analysis-dialog"><small>PERSISTENT JOB HISTORY</small><h2>Operations</h2><div class="jobs-list"><p>Loading…</p></div><div class="modal-actions"><button class="button ghost" data-clear-jobs type="button">Clear finished</button><button class="button primary" value="cancel">Close</button></div></div>`);
  try {
    const data = await api("/api/operations");
    const list = modalContent.querySelector(".jobs-list");
    list.innerHTML = data.operations.map(job => `<article class="job ${esc(job.state)}"><b>${esc(job.state)}</b><span><strong>${esc(job.message)}</strong><small>${job.total != null ? `${job.current || 0} of ${job.total}` : "No item count"} · ${new Date(job.updatedAt * 1000).toLocaleString()}${job.details?.completed?.length ? ` · ${job.details.completed.length} completed` : ""}${job.details?.skipped?.length ? ` · ${job.details.skipped.length} skipped` : ""}</small></span>${job.state === "running" ? `<button type="button" data-cancel-job="${esc(job.id)}">Abort</button>` : job.details?.resumable ? `<button type="button" data-resume-job="${esc(job.id)}">Resume</button>` : ""}</article>`).join("") || "<p>No retained operations.</p>";
    list.querySelectorAll("[data-cancel-job]").forEach(button => button.onclick = async () => { await api(`/api/operations/${button.dataset.cancelJob}/cancel`, { method: "POST" }); showJobsPanel(); });
    list.querySelectorAll("[data-resume-job]").forEach(button => button.onclick = async () => {
      const job = data.operations.find(item => item.id === button.dataset.resumeJob);
      const details = job?.details;
      if (!details?.request?.items) return toast("This operation has no resumable item plan.", true);
      // A completed or skipped item is identified by the source it names, so
      // a resume re-submits only what has not been dealt with.
      const done = new Set([...(details.completed || []), ...(details.skipped || [])].map(item => String(item.source ?? "")));
      const request = { ...details.request, items: details.request.items.filter(item => !done.has(String(item.source ?? ""))), operationId: newUuid() };
      if (!request.items.length) return toast("No pending items remain.");
      button.disabled = true;
      try {
        const result = await api(details.endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
        const targetPane = panes.findIndex(pane => pane.image?.id === request.targetImage);
        if (targetPane >= 0) { panes[targetPane].image = result.image; await refreshCurrentView(targetPane); }
        toast(`Resumed job completed ${result.completed?.length || 0} remaining items`);
      } catch (error) { toast(`Resume paused: ${error.message}`, true); }
      showJobsPanel();
    });
    modalContent.querySelector("[data-clear-jobs]").onclick = async () => { await api("/api/operations", { method: "DELETE" }); showJobsPanel(); };
  } catch (error) { toast(error.message, true); }
}

async function exportWorkflowRecipe(index) {
  const pane = panes[index];
  if (!pane?.image) return toast("Choose an open image for the workflow recipe.", true);
  modal.close();
  showModal('<div class="analysis-loading"><span class="modal-progress-icon" aria-hidden="true">↻</span><h2>Building deterministic workflow</h2><p>Cataloguing the retained base and current image…</p></div>');
  modal.classList.add("busy");
  try {
    const response = await trackedPaneOperation(
      index,
      "Building deterministic workflow recipe",
      operationId => fetch(`/api/images/${pane.image.id}/workflow-recipe?${new URLSearchParams({ operationId })}`),
      { abortMode: "read-only" },
    );
    const result = await downloadResponse(
      response,
      `${pathNameWithoutExtension(pane.image.name)}-workflow.affrecipe.zip`,
    );
    modal.close();
    toast(`Deterministic workflow downloaded · ${humanSize(result.size)}`);
  } catch (error) {
    modal.close();
    toast(`Could not export workflow: ${error.message}`, true);
  }
}

function projectDocument() {
  return {
    format: "atari-file-forge-project",
    version: 2,
    created: new Date().toISOString(),
    panes: panes.map(pane => ({
      imageId: pane.image?.id || null, imageName: pane.image?.name || "", kind: pane.image?.kind || "",
      partition: pane.partition, side: pane.side, path: pane.path,
      hardwareProfile: pane.image?.hardwareProfile || {}, windowState: pane.windowState,
    })),
    hardwareProfiles: storedHardwareProfiles(),
    importRecipes: storedCollection(RECIPE_STORAGE_KEY, []),
  };
}

async function importProjectFile(file) {
  const project = JSON.parse(await file.text());
  if (project.format !== "atari-file-forge-project" || !Array.isArray(project.panes)) throw new Error("This is not an Atari File Forge project file.");
  saveCollection(PROFILE_STORAGE_KEY, project.hardwareProfiles || BUILTIN_PROFILES);
  saveCollection(RECIPE_STORAGE_KEY, project.importRecipes || []);
  const saved = project.panes;
  persistentStorage.setItem(OPEN_PANES_STORAGE_KEY, JSON.stringify(saved.map(item => ({
    imageId: item?.imageId || null,
    partition: item?.partition ?? null,
    side: item?.side ?? null,
    path: typeof item?.path === "string" ? item.path : "",
    windowState: item?.windowState || null,
  }))));
  panes.splice(0, panes.length, ...Array.from({ length: Math.max(1, saved.length) }, () => newPaneState()));
  await restoreOpenPanes();
  toast("Project workspace restored");
}

let workbenchRenderSequence = 0;

async function renderWorkbench(section = "profiles") {
  const renderSequence = ++workbenchRenderSequence;
  const hardware = await hardwareProfileCatalogue();
  if (renderSequence !== workbenchRenderSequence) return;
  const profiles = storedHardwareProfiles();
  const activeProfile = activeWorkbenchProfile(profiles);
  const recipes = storedCollection(RECIPE_STORAGE_KEY, []);
  const imageOptions = panes.map((pane, index) => pane.image ? `<option value="${index}">${esc(paneLabel(index))}</option>` : "").join("");
  showModal(`<div class="workbench-dialog"><header><div><small>ATARI FILE FORGE</small><h2>Workbench</h2></div><select name="workbenchSection"><option value="profiles" ${section === "profiles" ? "selected" : ""}>Hardware profiles</option><option value="recipes" ${section === "recipes" ? "selected" : ""}>Import recipes</option><option value="project" ${section === "project" ? "selected" : ""}>Portable project</option></select></header>
    ${section === "profiles" ? `<div class="workbench-profile-picker field"><label>Hardware profile</label><select name="profileSelect">${profiles.map((profile, index) => `<option value="${index}">${esc(profile.name)}</option>`).join("")}</select><small>Start with a common system, then build the exact target from compatible additions.</small></div><div class="workbench-grid workbench-profile-grid"><section><div class="field"><label>Profile name</label><input name="profileName" value="${esc(profiles[0]?.name || "My Atari setup")}"></div><div class="field"><label>Base machine</label><select name="profileMachine">${hardware.machines.map(machine => `<option value="${esc(machine.id)}">${esc(machine.label)} · ${esc(machine.baseRam)} · ${esc(machine.processor)}</option>`).join("")}</select></div><div class="field"><label>Online Library filter</label><select name="profileCatalogMachine">${ONLINE_MACHINES.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}</select></div><div class="field"><label>Filing system</label><select name="profileFs">${WORKBENCH_FILE_SYSTEMS.map(([value,label]) => `<option value="${value}">${label}</option>`).join("")}</select></div><div class="field"><label>Target validation</label><select name="profileTarget">${TARGET_MEDIA.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}</select></div><div class="field"><label>Hard-disk driver</label><select name="profileDriver">${DRIVE_DRIVER_BUILDS.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}</select></div><div class="field"><label>Program flags</label><input name="profilePage" value="${esc(profiles[0]?.page || "0")}"><small>The <code>_p_flags</code> longword a program header on this machine is expected to carry.</small></div><section class="workbench-addon-builder"><header><div><small>COMPATIBLE HARDWARE</small><h3>Add-ons</h3></div><span data-addon-summary></span></header><div class="hardware-addon-groups" data-hardware-addons></div></section><details class="workbench-emulator-settings" open><summary>Emulator and debugger integration</summary><div class="help-note"><strong>Managed tools:</strong> Atari File Forge translates supported additions into Hatari machine types, memory sizes, floppy and hard-drive attachments, processor options and monitor modes. Items marked Validation only still affect compatibility analysis but are not falsely claimed as emulated.</div><div class="workbench-emulator-controls"><div class="field"><label>Emulator</label><select name="profileEmulator">${WORKBENCH_EMULATORS.map(([value,label]) => `<option value="${value}">${label}</option>`).join("")}</select></div><div class="field"><label>Debugger</label><select name="profileDebugger">${WORKBENCH_DEBUGGERS.map(([value,label]) => `<option value="${value}">${label}</option>`).join("")}</select></div><div class="field"><label>Emulated RAM</label><select name="profileEmulatorRam"><option value="auto">From base machine and add-ons</option>${WORKBENCH_MEMORY.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}</select></div><div class="field"><label>Startup action</label><select name="profileEmulatorBoot"><option value="auto">Use image default</option><option value="boot">Boot from this image</option><option value="catalogue">Open catalogue only</option></select></div></div></details><div class="help-note"><strong>Applies to the whole workspace.</strong> Every open image takes this profile, and so does every image opened or created afterwards, until another profile is applied.</div><div class="modal-actions"><button type="button" class="button" data-save-profile>Save profile</button><button type="button" class="button primary" data-apply-profile>Apply profile</button></div></section></div>` : section === "recipes" ? `<div class="workbench-grid"><aside>${recipes.map((recipe, index) => `<button type="button" data-recipe-index="${index}"><b>${esc(recipe.name)}</b><small>${esc(recipe.naming)} · ${recipe.addMenu ? "menu" : "off-menu"}</small></button>`).join("") || "<p>No saved recipes yet.</p>"}</aside><section><div class="field"><label>Recipe name</label><input name="recipeName" value="Collection import"></div><div class="field"><label>Folder naming</label><select name="recipeNaming"><option value="source">Use source titles</option><option value="generic">DISK0000 sequence</option></select></div><div class="field"><label>Group prefix</label><input name="recipeGroup" maxlength="8" value="DISKS"></div><label class="check-field"><input type="checkbox" name="recipeOnline" checked> Use online metadata for ambiguous titles</label><label class="check-field"><input type="checkbox" name="recipeCompat" checked> Rewrite host names to GEMDOS 8.3 automatically</label><label class="check-field"><input type="checkbox" name="recipeMenu" checked> Offer imported titles to a menu</label><div class="modal-actions"><button type="button" class="button primary" data-save-recipe>Save recipe</button></div></section></div>` : `<div class="project-tools"><p>A project description preserves the pane layout, working session references, current paths, profiles and recipes. Image bytes remain in their private recoverable sessions and normal timestamped save ZIPs. Theme remains a browser preference.</p><div class="modal-actions"><button type="button" class="button" data-export-project>Export project JSON</button><label class="button primary">Import project JSON<input type="file" accept="application/json,.json" data-import-project hidden></label></div><hr><h3>Deterministic workflow</h3><p>Export the earliest retained pre-change checkpoint identity, a guarded patch containing every later filesystem change, and the exact hashes expected from a successful rebuild. Original image bytes are not included.</p><label class="field"><span>Completed image</span><select name="workflowPane">${imageOptions || '<option value="">No open images</option>'}</select></label><div class="help-note">The CLI verifies the base image, the patch and the final saved output. Flux workflows remain unavailable until their container-level reconstruction is provably lossless.</div><div class="modal-actions"><button type="button" class="button primary" data-export-workflow ${imageOptions ? "" : "disabled"}>Export workflow bundle</button></div></div>`}
    <div class="modal-actions"><button class="button primary" value="cancel">Close workbench</button></div></div>`, null, { replace: modal.open });
  modalContent.querySelector('[name="workbenchSection"]').onchange = event => renderWorkbench(event.target.value);
  if (section === "profiles") wireProfileWorkbench(profiles, activeProfile.index, hardware);
  if (section === "recipes") wireRecipeWorkbench(recipes);
  modalContent.querySelector("[data-export-project]")?.addEventListener("click", () => downloadDocument(`atari-file-forge-${new Date().toISOString().replace(/[:.]/g, "-")}.aff-project.json`, JSON.stringify(projectDocument(), null, 2)));
  modalContent.querySelector("[data-import-project]")?.addEventListener("change", async event => { try { await importProjectFile(event.target.files[0]); modal.close(); } catch (error) { toast(error.message, true); } });
  modalContent.querySelector("[data-export-workflow]")?.addEventListener("click", () => exportWorkflowRecipe(Number(modalContent.querySelector('[name="workflowPane"]').value)));
}

function wireProfileWorkbench(profiles, initialIndex = 0, catalogue) {
  let selectedIndex = initialIndex;
  const hardwareMachineIds = () => (catalogue?.machines || []).map(machine => machine.id);
  const machineDefaults = {
    st: { addons: ["tos-104", "ram-1m", "drive-a-ds", "monitor-colour", "auto-folder"], catalogMachine: "st", filingSystem: "fat12", targetHardware: "floppy", driverBuild: "none", page: "0", emulator: "hatari", debugger: "hatari-debug", ram: "1M" },
    megast: { addons: ["tos-104", "ram-2m", "drive-a-ds", "blitter", "monitor-mono", "auto-folder"], catalogMachine: "megast", filingSystem: "fat12", targetHardware: "floppy", driverBuild: "none", page: "0", emulator: "hatari", debugger: "hatari-debug", ram: "2M" },
    ste: { addons: ["tos-162", "ram-1m", "drive-a-ds", "monitor-colour", "auto-folder"], catalogMachine: "ste", filingSystem: "fat12", targetHardware: "floppy", driverBuild: "none", page: "0", emulator: "hatari", debugger: "hatari-debug", ram: "1M" },
    megaste: { addons: ["tos-206", "ram-4m", "hd-floppy", "scsi-internal", "driver-hddriver", "monitor-mono", "desktop-inf"], catalogMachine: "megaste", filingSystem: "fat16", targetHardware: "hd", driverBuild: "hddriver", page: "0", emulator: "hatari", debugger: "hatari-debug", ram: "4M" },
    tt030: { addons: ["tos-306", "ram-2m", "tt-ram", "hd-floppy", "scsi-internal", "driver-hddriver", "fpu-68882", "monitor-vga", "desktop-inf"], catalogMachine: "tt030", filingSystem: "fat16", targetHardware: "hd", driverBuild: "hddriver", page: "0", emulator: "hatari", debugger: "hatari-debug", ram: "2M" },
    falcon030: { addons: ["tos-4xx", "ram-14m", "hd-floppy", "ide-internal", "driver-hddriver", "fpu-68882", "monitor-vga", "desktop-inf"], catalogMachine: "falcon030", filingSystem: "fat16", targetHardware: "hd", driverBuild: "hddriver", page: "0", emulator: "hatari", debugger: "hatari-debug", ram: "14M" },
  };
  const selectedAddons = () => [
    ...[...modalContent.querySelectorAll('[name="profileAddon"]:checked')].map(input => input.value),
    ...[...modalContent.querySelectorAll('[name="profileAddonSelect"]')].map(select => select.value).filter(Boolean),
  ];
  const updateAddonSummary = () => {
    const values = selectedAddons();
    const emulated = values.filter(id => catalogue.addons.find(addon => addon.id === id)?.emulator !== "profile").length;
    const summary = modalContent.querySelector("[data-addon-summary]");
    if (summary) summary.textContent = `${values.length} selected · ${emulated} emulator-driven`;
  };
  const refreshAddonDescriptions = () => {
    modalContent.querySelectorAll('[name="profileAddonSelect"]').forEach(select => {
      const addon = catalogue.addons.find(item => item.id === select.value);
      const detail = select.closest(".hardware-addon-select")?.querySelector("[data-addon-description]");
      if (detail) detail.textContent = addon ? `${addon.description} · ${addon.emulator === "profile" ? "Validation only" : `Driven by ${addon.emulator}`}` : "No additional hardware selected.";
    });
  };
  const addonControl = id => modalContent.querySelector(`[name="profileAddon"][value="${CSS.escape(id)}"]`)
    || [...modalContent.querySelectorAll('[name="profileAddonSelect"]')].find(select => [...select.options].some(option => option.value === id));
  const addonSelected = id => selectedAddons().includes(id);
  const setAddonSelected = (id, selected) => {
    const control = addonControl(id);
    if (!control) return;
    if (control.matches('[type="checkbox"]')) control.checked = selected;
    else control.value = selected ? id : "";
  };
  const requirementChoices = requirement => {
    const [scope, expression] = requirement.includes(":") ? requirement.split(":", 2) : [null, requirement];
    const machine = modalContent.querySelector('[name="profileMachine"]').value;
    return scope && scope !== machine ? [] : expression.split("|");
  };
  const selectRequirements = identifier => {
    const addon = catalogue.addons.find(item => item.id === identifier);
    (addon?.requires || []).forEach(requirement => {
      const choices = requirementChoices(requirement);
      if (!choices.length || choices.some(addonSelected)) return;
      if (!addonControl(choices[0])) return;
      setAddonSelected(choices[0], true);
      selectRequirements(choices[0]);
    });
  };
  const removeInvalidDependants = () => {
    let changed = true;
    while (changed) {
      changed = false;
      selectedAddons().forEach(identifier => {
        const addon = catalogue.addons.find(item => item.id === identifier);
        const valid = (addon?.requires || []).every(requirement => {
          const choices = requirementChoices(requirement);
          return !choices.length || choices.some(addonSelected);
        });
        if (!valid) { setAddonSelected(identifier, false); changed = true; }
      });
    }
  };
  const wireAddonInputs = () => {
    modalContent.querySelectorAll('[name="profileAddon"], [name="profileAddonSelect"]').forEach(input => input.onchange = () => {
      const identifier = input.matches("select") ? input.value : input.value;
      const selected = input.matches("select") ? Boolean(input.value) : input.checked;
      if (input.matches('[type="checkbox"]') && input.checked) {
        const group = input.closest("[data-addon-group]");
        const limit = Number(group?.dataset.addonMax || 0);
        const checked = group ? group.querySelectorAll('[name="profileAddon"]:checked').length : 0;
        if (limit && checked > limit) {
          input.checked = false;
          toast(`Choose no more than ${limit} option${limit === 1 ? "" : "s"} from this hardware group.`, true);
          updateAddonSummary();
          return;
        }
      }
      if (selected) {
        const addon = catalogue.addons.find(item => item.id === identifier);
        (addon?.conflicts || []).forEach(conflict => {
          // A single-choice group is a dropdown, so it is already exclusive.
          // Clearing a conflicting option that lives in the same control would
          // wipe the choice just made, which is why every processor used to
          // reset itself to None the moment it was picked.
          const control = addonControl(conflict);
          if (!control || control === input) return;
          setAddonSelected(conflict, false);
        });
        selectRequirements(identifier);
      }
      else removeInvalidDependants();
      refreshAddonDescriptions();
      const values = selectedAddons();
      // Storage decides the filing system: a floppy is FAT12 and a hard drive
      // is FAT16, and a drive needs a driver unless EmuTOS is reading it.
      const hasDrive = ["acsi-megafile", "acsi-third-party", "acsi2stm", "ultrasatan", "cosmosex", "ide-internal", "ide-adapter", "scsi-internal", "cf-adapter"].some(id => values.includes(id));
      modalContent.querySelector('[name="profileFs"]').value = hasDrive ? "fat16" : "fat12";
      modalContent.querySelector('[name="profileTarget"]').value = hasDrive ? "hd" : "floppy";
      if (hasDrive && modalContent.querySelector('[name="profileDriver"]').value === "none") {
        modalContent.querySelector('[name="profileDriver"]').value = values.includes("driver-emutos-builtin") ? "emutos" : "hddriver";
      }
      if (!hasDrive) modalContent.querySelector('[name="profileDriver"]').value = "none";
      applyDependencies();
      updateAddonSummary();
    });
    refreshAddonDescriptions();
    updateAddonSummary();
  };
  const renderAddons = selected => {
    const host = modalContent.querySelector("[data-hardware-addons]");
    host.innerHTML = hardwareAddonMarkup(catalogue, modalContent.querySelector('[name="profileMachine"]').value, selected);
    wireAddonInputs();
  };
  const applyDependencies = profile => {
    // A driver is only meaningful once the profile has a hard drive to boot
    // from; a floppy-only machine boots from TOS in ROM.
    const usesDrive = modalContent.querySelector('[name="profileFs"]').value.startsWith("fat16");
    modalContent.querySelector('[name="profileDriver"]').disabled = !usesDrive;
    if (!usesDrive) modalContent.querySelector('[name="profileDriver"]').value = "none";
  };
  const fill = profile => {
    // A profile saved by an older release can name a machine or a filing
    // system this build no longer offers, so each field falls back to the
    // default rather than leaving a select showing nothing.
    const machines = new Set(hardwareMachineIds());
    modalContent.querySelector('[name="profileName"]').value = profile.name || "";
    modalContent.querySelector('[name="profileMachine"]').value = machines.has(profile.machine) ? profile.machine : "st";
    modalContent.querySelector('[name="profileCatalogMachine"]').value = onlineMachineFromProfile(profile) || "all";
    modalContent.querySelector('[name="profileFs"]').value = WORKBENCH_FILE_SYSTEMS.some(([value]) => value === profile.filingSystem) ? profile.filingSystem : "fat12";
    modalContent.querySelector('[name="profileTarget"]').value = TARGET_MEDIA.some(([value]) => value === profile.targetHardware) ? profile.targetHardware : "auto";
    modalContent.querySelector('[name="profileDriver"]').value = DRIVE_DRIVER_BUILDS.some(([value]) => value === profile.driverBuild) ? profile.driverBuild : "none";
    modalContent.querySelector('[name="profilePage"]').value = profile.page || "0";
    renderAddons(profile.addons || []);
    modalContent.querySelector('[name="profileEmulator"]').value = profile.emulator || "auto";
    modalContent.querySelector('[name="profileDebugger"]').value = profile.debugger || "auto";
    const ram = modalContent.querySelector('[name="profileEmulatorRam"]');
    ram.value = [...ram.options].some(option => option.value === profile.emulatorRam) ? profile.emulatorRam : "auto";
    modalContent.querySelector('[name="profileEmulatorBoot"]').value = profile.emulatorBoot || "auto";
    applyDependencies(profile);
  };
  const read = () => { const addons = selectedAddons(); return ({ name: modalContent.querySelector('[name="profileName"]').value.trim() || "My Atari setup", machine: modalContent.querySelector('[name="profileMachine"]').value, addons, catalogMachine: modalContent.querySelector('[name="profileCatalogMachine"]').value, filingSystem: modalContent.querySelector('[name="profileFs"]').value, targetHardware: modalContent.querySelector('[name="profileTarget"]').value, driverBuild: modalContent.querySelector('[name="profileDriver"]').value, page: modalContent.querySelector('[name="profilePage"]').value.trim(), accelerated: addons.some(id => id.startsWith("acc-")), menuType: "desktop", emulator: modalContent.querySelector('[name="profileEmulator"]').value, debugger: modalContent.querySelector('[name="profileDebugger"]').value, emulatorRam: modalContent.querySelector('[name="profileEmulatorRam"]').value, emulatorBoot: modalContent.querySelector('[name="profileEmulatorBoot"]').value }); };
  modalContent.querySelector('[name="profileSelect"]').onchange = event => {
    selectedIndex = Number(event.target.value);
    fill(profiles[selectedIndex]);
    setActiveWorkbenchProfile(selectedIndex, profiles[selectedIndex]);
  };
  modalContent.querySelector('[name="profileMachine"]').onchange = event => {
    const defaults = machineDefaults[event.target.value];
    if (!defaults) return;
    modalContent.querySelector('[name="profileCatalogMachine"]').value = defaults.catalogMachine;
    modalContent.querySelector('[name="profileFs"]').value = defaults.filingSystem;
    modalContent.querySelector('[name="profileTarget"]').value = defaults.targetHardware;
    modalContent.querySelector('[name="profileDriver"]').value = defaults.driverBuild;
    modalContent.querySelector('[name="profilePage"]').value = defaults.page;
    modalContent.querySelector('[name="profileEmulator"]').value = defaults.emulator;
    modalContent.querySelector('[name="profileDebugger"]').value = defaults.debugger;
    modalContent.querySelector('[name="profileEmulatorRam"]').value = defaults.ram;
    renderAddons(defaults.addons);
    applyDependencies();
  };
  modalContent.querySelector('[name="profileFs"]').onchange = () => applyDependencies();
  modalContent.querySelector('[name="profileEmulator"]').onchange = () => applyDependencies();
  modalContent.querySelector('[name="profileCatalogMachine"]').onchange = event => rememberOnlineMachine(event.target.value);
  modalContent.querySelector("[data-save-profile]").onclick = () => {
    profiles[selectedIndex] = read();
    setActiveWorkbenchProfile(selectedIndex, profiles[selectedIndex]);
    saveCollection(PROFILE_STORAGE_KEY, profiles);
    renderWorkbench("profiles");
    toast("Hardware profile saved");
  };
  modalContent.querySelector("[data-apply-profile]").onclick = async () => {
    // Every open image takes the profile, and making it the active one means
    // images opened afterwards take it too. Applying it to a single pane named
    // in a dropdown left the rest of the workspace describing a different
    // machine, which is a difference nothing on screen announced.
    const profile = read();
    const targets = panes
      .map((pane, index) => ({ pane, index }))
      .filter(({ pane }) => pane.image);
    for (const { pane, index } of targets) {
      const data = await api(`/api/images/${pane.image.id}/hardware-profile`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(profile) });
      pane.image = data.image;
      renderPane(index);
    }
    setActiveWorkbenchProfile(selectedIndex, profile);
    modal.close();
    toast(`${profile.name} applied to ${targets.length} open image${targets.length === 1 ? "" : "s"} and to whatever is opened next${profile.accelerated ? " · Accelerator compatibility warnings enabled" : ""}`);
  };
  if (profiles[selectedIndex]) {
    modalContent.querySelector('[name="profileSelect"]').value = String(selectedIndex);
    fill(profiles[selectedIndex]);
    setActiveWorkbenchProfile(selectedIndex, profiles[selectedIndex]);
  }
}

function wireRecipeWorkbench(recipes) {
  let selectedIndex = recipes.length;
  const fill = recipe => {
    modalContent.querySelector('[name="recipeName"]').value = recipe.name || "";
    modalContent.querySelector('[name="recipeNaming"]').value = recipe.naming || "source";
    modalContent.querySelector('[name="recipeGroup"]').value = recipe.groupPrefix || "DISKS";
    modalContent.querySelector('[name="recipeOnline"]').checked = recipe.online !== false;
    modalContent.querySelector('[name="recipeCompat"]').checked = recipe.compatibility !== false;
    modalContent.querySelector('[name="recipeMenu"]').checked = recipe.addMenu !== false;
  };
  modalContent.querySelectorAll("[data-recipe-index]").forEach(button => button.onclick = () => { selectedIndex = Number(button.dataset.recipeIndex); fill(recipes[selectedIndex]); });
  modalContent.querySelector("[data-save-recipe]").onclick = () => {
    const recipe = { name: modalContent.querySelector('[name="recipeName"]').value.trim() || "Collection import", naming: modalContent.querySelector('[name="recipeNaming"]').value, groupPrefix: modalContent.querySelector('[name="recipeGroup"]').value.trim() || "DISKS", online: modalContent.querySelector('[name="recipeOnline"]').checked, compatibility: modalContent.querySelector('[name="recipeCompat"]').checked, addMenu: modalContent.querySelector('[name="recipeMenu"]').checked };
    recipes[selectedIndex] = recipe; saveCollection(RECIPE_STORAGE_KEY, recipes); renderWorkbench("recipes"); toast("Import recipe saved");
  };
}

const storedTheme = persistentStorage.getItem("atari-file-forge-theme");
const initialTheme = storedTheme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
document.documentElement.dataset.theme = initialTheme;
const themeToggle = document.querySelector("#themeToggle");
document.querySelector("#addPaneButton").onclick = addPane;
const helpMenu = document.querySelector("#helpMenu");
// The header menu behaves like the pane menus: it closes when the pointer
// moves off it, when something outside it is clicked and on Escape.
wireDismissibleMenu(helpMenu);
document.querySelector("#helpGuideButton").onclick = () => { helpMenu.open = false; showHelp(); };
document.querySelector("#aboutButton").onclick = () => { helpMenu.open = false; showAbout(); };
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && helpMenu.open) {
    helpMenu.open = false;
    helpMenu.querySelector("summary")?.focus();
  }
});
document.querySelector("#workbenchButton").onclick = () => renderWorkbench();
document.querySelector("#jobsButton").onclick = showJobsPanel;
document.querySelector("#workspaceSearchButton").onclick = showWorkspaceSearch;
document.querySelector("#collectionButton").onclick = () => showCollectionCatalogue();
document.addEventListener("keydown", event => {
  const editing = event.target.closest("input, textarea, select, [contenteditable=true]");
  if (editing || modal.open) return;
  if (event.key === "Escape" && workspaceClipboard) {
    event.preventDefault();
    clearWorkspaceClipboard("Clipboard cancelled.");
    return;
  }
  if (!(event.ctrlKey || event.metaKey)) return;
  const paneHost = event.target.closest(".pane[data-pane]");
  if (!paneHost) return;
  const index = Number(paneHost.dataset.pane);
  const key = event.key.toLowerCase();
  if (key === "c" || key === "x") {
    event.preventDefault();
    setWorkspaceClipboard(index, key === "x" ? "cut" : "copy");
  } else if (key === "v" && workspaceClipboard) {
    event.preventDefault();
    pasteWorkspaceClipboard(index);
  }
});
window.addEventListener("beforeunload", captureActiveEditorDocument);
let jobsBadgeRefreshTimer = null;
let jobsBadgeRefreshInFlight = false;
function scheduleJobsBadgeRefresh(delay) {
  clearTimeout(jobsBadgeRefreshTimer);
  jobsBadgeRefreshTimer = setTimeout(refreshJobsBadge, delay);
}
async function refreshJobsBadge() {
  if (document.hidden) {
    scheduleJobsBadgeRefresh(30000);
    return;
  }
  if (jobsBadgeRefreshInFlight) return;
  jobsBadgeRefreshInFlight = true;
  let nextRefresh = 30000;
  try {
    const data = await api("/api/operations");
    const active = data.operations.filter(item => ["running", "cancelling", "paused", "failed", "interrupted"].includes(item.state)).length;
    const badge = document.querySelector("#jobsBadge");
    badge.hidden = active === 0;
    badge.textContent = String(active);
    nextRefresh = active ? 3000 : 30000;
  } catch (_error) { /* The app remains usable if job history is unavailable. */ }
  jobsBadgeRefreshInFlight = false;
  scheduleJobsBadgeRefresh(nextRefresh);
}
refreshJobsBadge();
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshJobsBadge();
});
function updateThemeButton() {
  const dark = document.documentElement.dataset.theme === "dark";
  themeToggle.querySelector("b").textContent = dark ? "Light" : "Dark";
  themeToggle.setAttribute("aria-label", `Switch to ${dark ? "light" : "dark"} mode`);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#1e1e1e" : "#d8d4c8");
}
themeToggle.onclick = () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  persistentStorage.setItem("atari-file-forge-theme", next);
  updateThemeButton();
};
updateThemeButton();
updateAddPaneButton();

window.AtariDesktopHost = Object.freeze({
  paneAtPoint(x, y) {
    const host = document.elementFromPoint(Number(x), Number(y))?.closest?.(".pane");
    const index = Number(host?.dataset?.pane);
    return Number.isInteger(index) ? index : -1;
  },
  chooserOpened(preferredIndex = null) {
    const paneNumber = Number.isInteger(preferredIndex) ? preferredIndex + 1 : null;
    toast(`Native file chooser opened${paneNumber ? ` for pane ${paneNumber}` : ""}`);
  },
  reviewSelection(files = [], preferredIndex = null) {
    const selected = Array.isArray(files)
      ? files.filter(file => file && typeof file.path === "string" && typeof file.name === "string")
      : [];
    if (!selected.length) return toast("The native chooser did not return a usable image.", true);
    const allRom = selected.length > 1 && selected.every(file => formats.isRomImage(file.name));
    const hasGemdos = selected.some(file => formats.isPotentialGemdosImage(file.name));
    const equalRomSize = allRom && selected.every(file => Number(file.size) === Number(selected[0].size));
    const canInterleave = equalRomSize && [2, 4].includes(selected.length);
    showModal(`<div class="modal-heading"><span class="modal-kicker">OPEN LOCAL MEDIA</span><h2>Review selected image${selected.length === 1 ? "" : "s"}</h2><p>The native host reads these paths directly. The same format and target-media decisions used by the web host are applied before a private working copy is created.</p></div>
      <div class="folder-import-preview">${selected.map((file, order) => `<code>${order + 1}. ${esc(file.name)} · ${humanSize(file.size)}</code>`).join("")}</div>
      ${hasGemdos ? `<div class="field"><label>Target media</label><select name="targetHardware">${TARGET_MEDIA.map(([value, label]) => `<option value="${value}">${esc(label)}</option>`).join("")}</select><small>Used only for an image that may hold a GEMDOS volume.</small></div>` : ""}
      ${allRom ? `<div class="field"><label>Multiple ROM files</label><select name="romSetMode"><option value="separate">Open as separate ROM images</option><option value="linear">One component set · consecutive banks</option>${canInterleave ? `<option value="byte-interleaved-${selected.length}">One component set · ${selected.length}-way byte interleave</option>` : ""}</select><small>${canInterleave ? "Choose a component-set layout only when these files are physical chips from one logical ROM." : "Interleaving requires two or four equal-sized components."}</small></div><div class="field"><label>ROM platform</label><select name="romPlatform"><option value="tos">TOS ROM · 192 KiB, 256 KiB or 512 KiB</option><option value="cartridge">Cartridge · 128 KiB at &amp;FA0000</option><option value="custom">Custom expansion or diagnostic ROM</option></select></div>` : selected.length === 1 ? '<div class="field"><label>Raw format override</label><select name="formatOverride"><option value="">Auto-detect</option><option value="rom">Open selected bytes as an Atari ROM</option></select><small>Use this for a headerless ROM with a generic filename.</small></div>' : ""}
      <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="open">Open selected image${selected.length === 1 ? "" : "s"}</button></div>`, form => {
        const targetHardware = String(form.get("targetHardware") || "auto");
        const romSetMode = String(form.get("romSetMode") || "separate");
        const reservedPanes = new Set();
        const reservePane = preferred => {
          if (Number.isInteger(preferred) && panes[preferred] && !reservedPanes.has(preferred)) {
            reservedPanes.add(preferred);
            return preferred;
          }
          let target = panes.findIndex((pane, index) => !pane.image && !reservedPanes.has(index));
          if (target < 0) target = addPane();
          reservedPanes.add(target);
          return target;
        };
        const plans = allRom && romSetMode !== "separate" ? [{
          paths: selected.map(file => file.path),
          preferredPane: reservePane(preferredIndex),
          forceKind: "rom",
          targetHardware: "auto",
          rom: {
            layout: romSetMode,
            platform: String(form.get("romPlatform") || "tos"),
            componentNames: selected.map(file => file.name),
          },
        }] : selected.map((file, offset) => ({
          paths: [file.path],
          preferredPane: reservePane(offset === 0 ? preferredIndex : null),
          targetHardware: formats.isPotentialGemdosImage(file.name) ? targetHardware : "auto",
          forceKind: (allRom || (selected.length === 1 && form.get("formatOverride") === "rom")) ? "rom" : "",
        }));
        window.webkit.messageHandlers.atariDesktop.postMessage(JSON.stringify({ command: "open-plans", plans }));
      });
      const targetSelect = modalContent.querySelector('[name="targetHardware"]');
      const profileTarget = activeWorkbenchProfile().profile?.targetHardware || "auto";
      if (targetSelect && [...targetSelect.options].some(option => option.value === profileTarget)) targetSelect.value = profileTarget;
      const platformSelect = modalContent.querySelector('[name="romPlatform"]');
      if (platformSelect && ["tt030", "falcon030"].includes(activeWorkbenchProfile().profile?.machine)) platformSelect.value = "tos";
  },
  showOpening(name, preferredIndex = null) {
    let index = Number.isInteger(preferredIndex) && panes[preferredIndex]
      ? preferredIndex
      : panes.findIndex(pane => !pane.image);
    // Progress is drawn inside the pane the image is destined for, so with
    // nowhere to draw it the operator watches a still workspace while the
    // work happens. Make somewhere.
    if (index < 0) index = addPane();
    // That pane can be underneath another window, which hides the progress
    // just as completely. Raise it, the way opening an image raises the pane
    // it lands in.
    paneWindowManager.bringToFront(index);
    setLoading(
      index,
      true,
      `Creating a private local working copy of ${name}, then validating its filesystem…`,
    );
  },
  applyNativeAppearance(appearance = {}) {
    document.documentElement.classList.add("native-desktop");
    const family = String(appearance.font || "system-ui")
      .replace(/\s+\d+(?:\.\d+)?$/, "")
      .replace(/["']/g, "")
      .trim();
    if (family) {
      document.documentElement.style.setProperty(
        "--desktop-font-family",
        `"${family}", system-ui, sans-serif`,
      );
    }
    if (!persistentStorage.getItem("atari-file-forge-theme")) {
      document.documentElement.dataset.theme = appearance.dark ? "dark" : "light";
      updateThemeButton();
    }
  },
  async acceptImage(image, preferredIndex = null) {
    if (!workspacePersistence.isReady()) {
      setTimeout(() => window.AtariDesktopHost.acceptImage(image, preferredIndex), 50);
      return;
    }
    let index = Number.isInteger(preferredIndex) && panes[preferredIndex]
      ? preferredIndex
      : panes.findIndex(pane => !pane.image);
    if (index < 0) index = addPane();
    try {
      await acceptImage(index, image);
      paneWindowManager.bringToFront(index);
      rememberOpenPanes();
      toast(`${image.name} opened from the Linux desktop`);
    } catch (error) {
      toast(`Could not display ${image.name}: ${error.message}`, true);
    }
  },
  sourceFolderChosen(folder) {
    // The native folder chooser answers here. An empty string means the
    // operator cancelled, which is an answer too.
    const waiting = pendingSourceFolder;
    pendingSourceFolder = null;
    if (waiting) waiting(String(folder || ""));
  },
  showError(message, paneIndex = null) {
    toast(String(message || "The Linux desktop operation failed."), true);
    // A pane was put into the opening state before the work started, and
    // nothing else takes it out again. Left alone it goes on saying it is
    // working on an image that was refused seconds ago, which reads as the
    // application having hung rather than having answered.
    const stopWaiting = index => {
      const pane = panes[index];
      if (!pane || !pane.loading || pane.image) return;
      setLoading(index, false);
    };
    if (Number.isInteger(paneIndex)) {
      stopWaiting(paneIndex);
      return;
    }
    // Without a pane number, every pane still waiting for an image it has
    // not got is waiting for this. An open that is genuinely still running
    // has an image by now, or is about to replace this state itself.
    panes.forEach((_pane, index) => stopWaiting(index));
  },
});

let desktopStorageSyncInstalled = false;
let desktopStorageTimer = null;
const DESKTOP_TRANSIENT_STORAGE_KEYS = new Set(["atari-file-forge-session-owner"]);

function localStorageSnapshot() {
  return Object.fromEntries(
    Array.from({ length: localStorage.length }, (_unused, index) => localStorage.key(index))
      .filter(key => key && !DESKTOP_TRANSIENT_STORAGE_KEYS.has(key))
      .map(key => [key, localStorage.getItem(key) ?? ""]),
  );
}

async function hydrateDesktopClientState() {
  const state = await api("/api/desktop/client-state");
  localStorage.clear();
  Object.entries(state.localStorage || {}).forEach(([key, value]) => {
    if (DESKTOP_TRANSIENT_STORAGE_KEYS.has(key)) return;
    localStorage.setItem(key, String(value));
  });
  const persist = () => {
    clearTimeout(desktopStorageTimer);
    desktopStorageTimer = setTimeout(() => {
      api("/api/desktop/client-state", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ localStorage: localStorageSnapshot() }),
      }).catch(error => toast(`Could not retain Linux desktop preferences: ${error.message}`, true));
    }, 150);
  };
  if (!desktopStorageSyncInstalled) {
    persistentStorageChanged = persist;
    desktopStorageSyncInstalled = true;
  }
  let desktopCollection = structuredClone(state.collection || { images: [], settings: { key: "preferences", wanted: [] } });
  collectionCatalogue = window.AtariCollectionCatalogue.createRemote({
    uuid: newUuid,
    load: async () => structuredClone(desktopCollection),
    save: async collection => {
      desktopCollection = structuredClone(collection);
      await api("/api/desktop/client-state", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ collection }),
      });
    },
  });
  const retainedTheme = persistentStorage.getItem("atari-file-forge-theme");
  if (retainedTheme) {
    document.documentElement.dataset.theme = retainedTheme;
    updateThemeButton();
  }
}

async function startWorkbench() {
  try {
    const health = await rawApi("/api/health");
    platformContract = health.platform || platformContract;
    applicationVersion = health.version || applicationVersion;
    applicationEngine = health.engine || applicationEngine;
  } catch (_error) {
    // The shared web host remains the safe default when capability discovery fails.
  }
  if (platformContract.host === "desktop") {
    try {
      await hydrateDesktopClientState();
    } catch (error) {
      toast(`Could not restore Linux desktop preferences: ${error.message}`, true);
    }
  }
  await restoreOpenPanes();
}

startWorkbench();
