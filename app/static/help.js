(() => {
  "use strict";

  // The handbook is declared once, as an ordered list of sections. The table of
  // contents is generated from the same list, so a navigation link cannot drift
  // away from its section id and the navigation order cannot drift away from the
  // reading order. Every id is a plain slug.
  const SECTIONS = [
    {
      group: "START HERE",
      id: "help-start",
      title: "Open or create an image",
      body: `
            <h3>Open or create an image</h3>
            <p class="help-lead">Edits are made to a private working copy. The file you selected on your computer is never overwritten.</p>
            <div class="help-note"><strong>Start small:</strong> a new workspace opens with one full-workspace pane. Select <strong>Add Pane</strong> whenever you need another source, destination or scratch image. There is no fixed pane-count limit, and extra panes open as cascading windows.</div>
            <div class="help-workflow" aria-label="Typical Atari File Forge workflow">
              <span><b>1</b><strong>Open or create</strong><small>A private working image</small></span><i>&rarr;</i>
              <span><b>2</b><strong>Browse and edit</strong><small>Files, folders and partitions</small></span><i>&rarr;</i>
              <span><b>3</b><strong>Analyse</strong><small>Geometry, filing system, boot code</small></span><i>&rarr;</i>
              <span><b>4</b><strong>Save</strong><small>Timestamped ZIP and README</small></span>
            </div>
            <div class="help-task">
              <h4>Open an existing image</h4>
              <ol>
                <li>Choose any empty pane.</li>
                <li>Select <strong>Open image</strong>, or drag a floppy, hard disk, disc or ROM image from your computer onto the empty pane.</li>
                <li>Choose the image. Supported families are ST sector images, MSA and DIM containers, Pasti STX captures, HFE and SCP flux images, IPF preservation captures, hard disk images with a partition table, bare GEMDOS volumes, CD images, and TOS or cartridge ROMs. A ZIP may contain one supported image.</li>
                <li>Wait for the opening indicator. The file list appears when identification is complete. A hard disk opens on its partition table instead, because nothing is mounted until you choose a partition.</li>
              </ol>
              <p>Identification uses the bytes, not the file name. A sector image named <code>GAME.IMG</code> opens as a floppy, and an MSA named <code>DISK1.ST</code> opens as an MSA.</p>
            </div>
            <div class="help-task">
              <h4>Create a new image</h4>
              <ol>
                <li>Open <strong>File &rarr; New &rarr; New Image (current format)</strong>. The current pane format is preselected.</li>
                <li>An existing empty pane is used first. If every pane holds an image, another workspace window is added automatically. Existing work is not replaced.</li>
                <li>Choose one of the floppy geometries, an HFE or SCP wrapper around one of them, a hard disk with a partition plan, a bare GEMDOS volume, a blank ROM or a cartridge.</li>
                <li>Enter a volume label of up to eleven characters. It is written into the boot sector and as the volume-label entry in the root directory.</li>
                <li>The size field is read-only for a floppy, because the geometry fixes the byte count. It becomes editable for a hard disk and a bare volume, and remembers the last capacity you entered, such as <code>20MB</code> or <code>512MB</code>.</li>
                <li>For a hard disk, choose the partition-table kind and the partition plan. The plan is checked against the TOS release you selected before anything is written.</li>
                <li>Select <strong>Create image</strong>. The formatted image opens immediately as an editable working copy.</li>
                <li>Add content, then use <strong>Save Image</strong> in the pane heading to download it.</li>
              </ol>
            </div>
            <div class="help-note"><strong>Pane heading actions:</strong> after the orange changed indicator, the buttons create a New Blank Image, Load New Image, Save Image, Refresh View, Minimise, Maximise or restore, and Close Pane. The &times; close button offers Save and close, Close without saving, or Cancel whenever the image has changes.</div>
            <h4>Which new format should I choose?</h4>
            <div class="help-table-wrap"><table class="help-table"><caption class="visually-hidden">Supported image formats and their main limits</caption>
              <thead><tr><th>Format</th><th>Best used for</th><th>Important limit</th></tr></thead>
              <tbody>
                <tr><td>ST sector image</td><td>An ordinary GEMDOS floppy, 360K to 1.44M</td><td>The boot sector decides the geometry, not the file size</td></tr>
                <tr><td>MSA</td><td>A packed floppy as distributed online</td><td>Decodes to sectors; the packing is reproduced on save</td></tr>
                <tr><td>DIM</td><td>A floppy dumped by E-Copy</td><td>Carries its own geometry header</td></tr>
                <tr><td>STX (Pasti)</td><td>A capture of a protected disk</td><td>Read-only; the capture cannot be re-encoded honestly</td></tr>
                <tr><td>HFE / SCP</td><td>Gotek and flux-level floppy work</td><td>Written back only when a decode of the result matches</td></tr>
                <tr><td>IPF</td><td>A preservation capture of a protected disk</td><td>Read-only; the decoder library is not bundled</td></tr>
                <tr><td>Hard disk with a partition table</td><td>An ACSI, SCSI or IDE drive a machine boots</td><td>The TOS release limits the size of each partition</td></tr>
                <tr><td>Bare GEMDOS volume</td><td>One filing system with no table in front of it</td><td>Geometry is derived, then reported, rather than stored</td></tr>
                <tr><td>CD image</td><td>An ISO 9660 disc</td><td>Read-only; copy files out into writable media</td></tr>
                <tr><td>TOS ROM</td><td>A system ROM dump or a blank device</td><td>Bytes are decoded as a ROM, never as a file list</td></tr>
                <tr><td>Cartridge</td><td>An ST cartridge image</td><td>The header is checked; the code behind it is not</td></tr>
              </tbody>
            </table></div>`
    },
    {
      id: "help-desktop",
      title: "The Linux desktop edition",
      body: `
            <h3>The Linux desktop edition</h3>
            <p class="help-lead">The Linux desktop edition is the same Atari File Forge workbench in a native GTK 4 window. Format support, editors, validation and saved packages stay aligned with the Docker edition.</p>
            <div class="help-task">
              <h4>Install and launch</h4>
              <ol>
                <li>Stable releases provide separate Debian 13 and Ubuntu 24.04 packages for AMD64, ARM64 and ARMv7. Install the matching <code>.deb</code> with APT, for example <code>sudo apt install ./atari-file-forge_0.3.0-1~deb13_amd64.deb</code>. APT installs the required Python 3, GTK 4, Libadwaita, WebKitGTK 6 and GObject packages.</li>
                <li>For development from a project checkout, install those system packages and run <code>tools/install-linux-desktop.sh</code> instead.</li>
                <li>Launch <strong>Atari File Forge</strong> from the application menu. The package command is <code>atari-file-forge</code>; a checkout uses <code>tools/atari-file-forge-desktop</code>.</li>
                <li>Use the native folder button, <strong>File &rarr; Open image</strong> in a pane or <kbd>Ctrl</kbd>+<kbd>O</kbd> to select one or several images with the GTK chooser. You can also drag image files from the Linux file manager onto a pane. Native selection and drag and drop pass local paths to the private desktop service, so image bytes are not uploaded through the embedded browser.</li>
                <li>Several images open into successive available panes.</li>
                <li>Review the selection before it opens. The active Workbench profile supplies the initial target machine, which can be changed for this operation. Several ROM files may be opened separately or treated as one linear or byte-interleaved physical component set.</li>
              </ol>
            </div>
            <ul>
              <li>Chooser, file-association and file-manager selections use one serial opening queue, so two large images cannot race while their private sessions are created.</li>
              <li>The selected source is cloned by the filesystem when possible, or sparse-copied once into XDG application storage. The original is not changed in place.</li>
              <li>Large hard disk images bypass browser upload and spooling. Expensive hardware finalisation remains deferred to Save and reports its stages there.</li>
              <li>GTK and Libadwaita supply the title bar, window controls, application menu, chooser and symbolic header icons. The workbench inherits the desktop font and initially follows the system light or dark setting.</li>
              <li>A stable private owner recovers this Linux user's working sessions. Workspace settings, hardware profiles and the private collection catalogue are stored atomically under the XDG configuration directory, so a new random-port launch does not lose them.</li>
              <li>Saved ZIPs use the normal Linux Downloads directory and contain the same image, sidecars and README as the web edition.</li>
              <li>Hatari appears as a native window. In Docker it continues to appear in the browser display.</li>
              <li>Install the optional official Greaseweazle tools to write sector and HFE images to real disks.</li>
            </ul>
            <div class="help-task"><h4>Write a physical floppy with Greaseweazle</h4><ol>
              <li>Confirm <code>gw info</code> can see the connected device and that the Linux udev rules permit access.</li>
              <li>Open a supported floppy image.</li>
              <li>Choose <strong>Tools &rarr; Write physical floppy</strong>, or right-click the image title or coloured format badge.</li>
              <li>Select drive A, B, 0, 1, 2 or 3, insert the destination disk, then acknowledge that every existing byte on it will be overwritten.</li>
              <li>Follow the live cylinder, head and verification progress. Abort stops Greaseweazle, but leaves the physical disk potentially incomplete; the working image remains unchanged.</li>
              <li>Keep a sector disk only after the completion dialog confirms verification. HFE contains raw bitcells and cannot be automatically verified, so test that disk on suitable hardware.</li>
            </ol></div>
            <div class="help-note"><strong>Stable source:</strong> the working image is finalised and copied to a private snapshot before the physical write begins. Later edits cannot alter an in-progress disk, and the temporary image and its snapshot are removed afterwards.</div>
            <div class="help-note"><strong>One product, two hosts:</strong> the desktop application embeds the shared frontend and starts the shared API on a private random loopback port. A fresh launch token protects it, a separate mode-0600 owner identifies its sessions, and native-only path and state adapters are not exposed by the web host.</div>
            <div class="help-note"><strong>Icon opens no window:</strong> pull the current code and rerun <code>tools/install-linux-desktop.sh</code>. The launcher detects Ubuntu systems that deny WebKitGTK's Bubblewrap user namespace and enables the compatibility fallback only there. Set <code>ATARI_FILE_FORGE_DISABLE_WEBKIT_SANDBOX=0</code> to require sandboxing or <code>1</code> for diagnostic fallback. Run <code>~/.local/bin/atari-file-forge</code> in a terminal if startup diagnostics are still needed.</div>
            <div class="help-warning"><strong>Updating:</strong> install a newer <code>.deb</code> over the release package, or pull the new source and rerun the checkout installer when Python dependencies change. Working sessions remain under <code>~/.local/share/atari-file-forge</code>, or the configured XDG data directory.</div>`
    },
    {
      id: "help-workspace",
      title: "Workspace and selection",
      body: `
            <h3>Workspace, navigation and selection</h3>
            <figure><img src="/help/workspace.png" alt="Atari File Forge showing movable image panes and the Add Pane control"><figcaption>The workspace begins with one pane. Add and arrange as many movable image windows as the computer can comfortably display; each retains independent navigation, selection, refresh, progress and save controls.</figcaption></figure>
            <h4>Add, arrange and close panes</h4>
            <ol>
              <li>Select <strong>Add Pane</strong> in the header to add an empty cascading window. There is no fixed pane-count limit.</li>
              <li>Drag an empty part of a pane heading, or use the numbered grip at its left, to move it. Windows may overlap, and selecting any part of a window brings it to the front.</li>
              <li>Drag a pane to the left or right edge to fill that half, to a corner to fill that quarter, or to the top edge to maximise it. The translucent preview shows the result before release.</li>
              <li>Drag any pane edge or corner to resize it. A snapped pane begins resizing from its visible snapped rectangle rather than jumping back to its earlier size. The lower-right corner has a visible resize mark. Double-click the numbered grip or use the square heading button to maximise or restore it.</li>
              <li>When the browser or workspace changes size, free panes scale proportionally to remain useful and visible. Snapped panes continue to follow their selected side or corner.</li>
              <li>Select the line button to minimise a pane to the shelf at the bottom of the workspace. Select its shelf button to restore and focus it.</li>
              <li>With the numbered grip focused, use Alt+Left or Alt+Right to snap, Alt+Up to maximise, and Alt+Down to minimise without a pointer. Hold Shift as well to resize in 32-pixel steps.</li>
              <li>An empty pane is a convenient scratch area for creating a floppy, a hard disk, a bare volume or a ROM.</li>
              <li>Select &times; at the top-right to close that whole pane. Save changed images from the prompt, deliberately close without saving a download, or cancel. The server working copy remains available through Recovery.</li>
              <li>Open images, positions, sizes, snap layout, stacking order and minimised windows are remembered across a normal page refresh. A completely fresh workspace starts with one pane.</li>
            </ol>
            <div class="help-note"><strong>Two different drag operations:</strong> drag a heading or its numbered grip to move or snap the window. Drag file rows or the coloured format badge on a supported disk image to transfer content between images.</div>
            <div class="help-note"><strong>Familiar pane menus:</strong> File and Edit are always first, followed by View, Library, Analyse and Tools. File holds open, save, add and create commands. Edit holds Cut, Copy, Paste, Undo and Checkpoints. View holds refresh and the command that returns to a drive's partition table. The heading icons remain quick shortcuts for common image actions.</div>
            <div class="help-note"><strong>Free-space meter:</strong> the lower-right bar uses the volume's own allocation table. Green means under 70% used, orange means 70% or more, and red means 90% or more. Hover over it for used, free and total values. A partition table counts allocated space; opening a partition switches the meter to that volume's clusters. A read-only capture with no writable filing system shows a neutral striped meter.</div>
            <h4>Navigate an image</h4>
            <ol>
              <li>Double-click a folder to enter it. Double-click a file to open the BASIC, script, text, disassembly or hex editor selected from its contents.</li>
              <li>Double-click <strong>..</strong> to move to the parent folder, or select any breadcrumb to jump directly to that location.</li>
              <li>Inside a partition, use <strong>All partitions</strong> to return to the partition table. The partition you left remains selected and is scrolled back into view.</li>
              <li>Paths are shown the way GEMDOS writes them, with a backslash separator and an optional drive letter, as in <code>C:\\AUTO\\FOLDRXXX.PRG</code>. The root of a volume is written as nothing at all, so the breadcrumb for the root shows the drive or volume label alone.</li>
              <li>Select &#8635; in the pane heading to reread the current folder or partition table without closing the image.</li>
              <li>Click the image filename in the pane heading to edit it. Press <kbd>Enter</kbd> or click elsewhere to save, or press <kbd>Escape</kbd> to cancel. The format extension is retained. This renames the recovered and downloaded container, not the volume label inside it.</li>
            </ol>
            <h4>Read the file list</h4>
            <p>The file list has five columns. <strong>Name</strong> is the GEMDOS name, upper case, at most eight characters with an optional three character extension. <strong>Kind</strong> is what the application identified the entry as, such as a folder, a <code>0x601A</code> program, a BASIC listing, a desktop configuration file or plain data. <strong>Size</strong> is the length recorded in the directory entry. <strong>Modified</strong> is the FAT datestamp, which has two-second resolution. <strong>Attributes</strong> is the GEMDOS attribute byte printed as six letters.</p>
            <h4>Select one or several items</h4>
            <ol>
              <li>Click an item to select only it.</li>
              <li>Use <kbd>Ctrl</kbd>/<kbd>Cmd</kbd>-click to add or remove individual items.</li>
              <li>Use <kbd>Shift</kbd>-click to select the range between the anchor and the clicked row.</li>
              <li>Press <kbd>Ctrl</kbd>/<kbd>Cmd</kbd>-<kbd>A</kbd> while a row has focus to select every usable item in the current view.</li>
              <li>Start dragging any selected row to carry the complete selection.</li>
              <li>Point at a single row to reveal Rename and Delete beside its name. For a multiple selection, Rename is hidden and Delete applies to the whole selection with one confirmation.</li>
              <li>The Attributes column reveals the read-only control. It applies to one file, or to every applicable item in a multiple selection.</li>
            </ol>
            <div class="help-note"><strong>The orange dot means changed:</strong> the working image contains edits not yet downloaded. It clears after Save Image has successfully prepared the download and returns after the next edit. A failed save leaves the dot visible. It does not mean the original file has changed.</div>`
    },
    {
      id: "help-checkpoints",
      title: "Undo and checkpoints",
      body: `
            <h3>Undo changes and create named checkpoints</h3>
            <p class="help-lead">Every image-changing operation starts with an automatic restore point. This includes file and folder edits, transfers, compaction and save-time image finalisation. Renaming an image and applying a hardware profile change none of its contents, so they take no restore point and Undo leaves them as they are.</p>
            <div class="help-task">
              <h4>Undo the latest operation</h4>
              <ol>
                <li>Open <strong>Edit</strong> in the affected pane.</li>
                <li>Select <strong>Undo last change</strong>. The button is disabled until an automatic restore point exists.</li>
                <li>The confirmation names the operation that will be reversed. Confirm the undo. The most recent automatic point is restored and consumed.</li>
                <li>All panes showing that same image return to its root, or to a drive's partition table, and refresh from the restored bytes.</li>
                <li>Repeat to step backwards through earlier operations. Up to 20 recent automatic points are retained per image.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Create and restore a named checkpoint</h4>
              <ol>
                <li>Before a large reorganisation, open <strong>Edit &rarr; Checkpoints</strong>.</li>
                <li>Enter a useful name such as <code>Before reorganising AUTO</code>, then select <strong>Create named checkpoint</strong>.</li>
                <li>Return to the same dialog at any time to inspect named checkpoints and automatic undo points.</li>
                <li>Select &#8630; beside a checkpoint and confirm to restore it. The state being replaced is first retained as a new automatic undo point.</li>
                <li>Select &times; beside an unwanted checkpoint to delete only that snapshot.</li>
              </ol>
            </div>
            <div class="help-note"><strong>Large hard disk images:</strong> Atari File Forge asks the host filesystem for a copy-on-write clone. If cloning is unavailable, its safe-copy fallback preserves sparse zero ranges instead of writing unused capacity. Either form remains a complete byte-for-byte restore point.</div>
            <div class="help-warning"><strong>Checkpoints belong to the working session:</strong> they are private to the same browser owner and survive refreshes and container restarts, but clearing the recovered session or deleting the Docker work volume removes them too. Download important finished images separately.</div>`
    },
    {
      id: "help-files",
      title: "Working with files",
      body: `
            <h3>Create, modify and delete files and folders</h3>
            <p class="help-lead">GEMDOS records three things about a file: its name, its attribute byte and its datestamp. There is nowhere to keep a note beside a file, and no per-file permission set. Atari File Forge shows exactly those three and invents nothing else.</p>
            <div class="help-task">
              <h4>Names GEMDOS accepts</h4>
              <ol>
                <li>A name is at most eight characters, with an optional extension of at most three. The desktop shows it as <code>NAME.EXT</code>.</li>
                <li>Names are upper case. A lower-case host name is folded to upper case before it is written, and the review shows you the result first. The folding is ASCII only, because the Atari character set is not Latin-1 and folding its accented characters the way a Latin-1 table would produces the wrong byte.</li>
                <li>A volume label is a separate limit: up to eleven characters, held in one root-directory entry with the volume bit set.</li>
                <li>These characters are forbidden and are replaced during the review: <code>\\ / : * ? " &lt; &gt; | + , ; = [ ]</code> and the space.</li>
                <li>A path uses a backslash and an optional drive letter, as in <code>C:\\AUTO\\FOLDRXXX.PRG</code>. The root is written as nothing, so <code>C:</code> and <code>C:\\</code> mean the same place.</li>
                <li>The comparison is case-insensitive within one folder, so two host files that differ only in case cannot both be written there. The review reports the clash before anything is written.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Read and change the attributes</h4>
              <ol>
                <li>The <strong>Attributes</strong> column prints the GEMDOS attribute byte as the six letters <code>rhsvda</code>: read-only, hidden, system, volume label, directory and archive. A letter means the bit is set; a dash means it is not.</li>
                <li>An ordinary writable file reads <code>---&mdash;a</code> once the archive bit has been set by a write, and <code>------</code> before it. A folder reads <code>----d-</code>. The single volume-label entry in a root directory reads <code>---v--</code>.</li>
                <li>Select the attribute cell to change it, or open <strong>File &rarr; File properties</strong> for a selected file. Several files can be changed together.</li>
                <li>The volume-label and directory bits are not editable, because they describe what the entry is rather than how it is treated. Changing either would make the directory inconsistent.</li>
                <li>Changes are written into the directory entry. The file's own bytes are not rewritten.</li>
              </ol>
              <div class="help-note"><strong>Read-only is advice, not enforcement.</strong> GEMDOS refuses to open a read-only file for writing, and that is all it does. Atari File Forge refuses its own writes to one for the same reason, so the flag is not silently ignored.</div>
            </div>
            <div class="help-task">
              <h4>Read and change the datestamp</h4>
              <ol>
                <li>The <strong>Modified</strong> column is the FAT datestamp held in the directory entry: a packed date word and a packed time word. The time word stores seconds in units of two, so the resolution is two seconds and an odd second cannot be represented.</li>
                <li>An imported host file keeps its own modification time, rounded down to the nearest even second.</li>
                <li>A file with a datestamp GEMDOS cannot represent, which happens with dumps written by other tools, is shown as the stored value and flagged in the analysis report rather than being corrected silently.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Add one or more host files</h4>
              <ol>
                <li>Navigate the destination pane to the required folder.</li>
                <li>Open <strong>File &rarr; Insert File</strong> and choose one or more files.</li>
                <li>For each file, review the target name, its attributes and its datestamp.</li>
                <li>If a name is illegal for GEMDOS, accept the safe suggestion or type a valid replacement.</li>
                <li>Select <strong>Insert File</strong> in the dialog. Each successful insertion appears in the current view.</li>
                <li>For a multiple selection, choose <strong>Insert and apply to all remaining</strong> to accept each later file's own detected name and metadata without reopening the same review.</li>
              </ol>
              <p>Files copied from one Atari image to another keep their attribute byte and datestamp, because the destination directory entry has the same fields. A loose host file has no attribute byte, so it is written with everything clear and the archive bit set.</p>
            </div>
            <div class="help-task">
              <h4>Import one or more host folders</h4>
              <ol>
                <li>Navigate to the destination and choose <strong>File &rarr; Insert Folder &amp; Contents</strong>, or drag folders from the desktop onto the pane. Use drag and drop to select several top-level folders when your browser supports it.</li>
                <li>Review the preflight. Desktop housekeeping files are ignored and any target-name shortening is shown before the image changes.</li>
                <li>Keep <strong>Preserve folder structure</strong> to recreate the tree under the current folder, or choose <strong>Import all files here</strong> to flatten it.</li>
                <li>Tick the explicit replacement option only when existing files with the same target paths should be overwritten.</li>
                <li>When a later review repeats the same decision, use <strong>Apply to all remaining</strong>. Every item keeps its own detected name, attributes and datestamp.</li>
              </ol>
              <p>The complete batch uses one filesystem mount and one undo checkpoint, which is substantially quicker and safer than adding every small file separately.</p>
            </div>
            <div class="help-task">
              <h4>Create a folder</h4>
              <ol>
                <li>Navigate to the parent folder.</li>
                <li>Choose <strong>File &rarr; New &rarr; New folder</strong>, enter a legal name and select <strong>Create folder</strong>.</li>
                <li>Double-click the new folder to enter it, then add or drag content into it.</li>
              </ol>
              <p>A folder is a real directory entry with the directory bit set, at any depth. The root directory of a floppy is the exception: it is a fixed-size area whose entry count comes from the boot sector, typically 112 entries on a 720K disk. The pane reports how many of those remain.</p>
            </div>
            <div class="help-task">
              <h4>Rename or move an item</h4>
              <ol>
                <li>Point at a file or folder and select its pencil icon to rename it in place.</li>
                <li>Enter a legal leaf name and select <strong>Rename</strong>.</li>
                <li>Move an item by dragging its row onto a folder. To move several items together, select them first and drag any selected row.</li>
                <li>You can also open the same image in several panes, navigate each pane independently, then drag into the required destination pane.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Download or delete</h4>
              <ol>
                <li>Use the download arrow beside a file to download a ZIP containing the loose file and its metadata sidecar without changing the image. The sidecar records the real path, attribute byte, length and datestamp. Double-click opens the appropriate editor instead.</li>
                <li>To remove one or several items, select them and use any visible &times; on the selected rows, or press <kbd>Delete</kbd>.</li>
                <li>Read the single confirmation carefully. Deleting a folder recursively removes everything below it.</li>
              </ol>
            </div>`
    },
    {
      group: "MEDIA GUIDES",
      id: "help-floppy",
      title: "Floppy sector images",
      body: `
            <h3>ST floppy images: geometry and the boot sector</h3>
            <p class="help-lead">An ST floppy image is the sectors of the disk, in order, and nothing else. That makes it simple to read and impossible to identify from its length alone.</p>
            <h4>The geometries the application creates and reads</h4>
            <div class="help-table-wrap"><table class="help-table"><caption class="visually-hidden">Supported ST floppy geometries</caption>
              <thead><tr><th>Nominal size</th><th>Sides</th><th>Tracks</th><th>Sectors per track</th></tr></thead>
              <tbody>
                <tr><td>360K</td><td>1</td><td>80</td><td>9</td></tr>
                <tr><td>400K</td><td>1</td><td>80</td><td>10</td></tr>
                <tr><td>440K</td><td>1</td><td>80</td><td>11</td></tr>
                <tr><td>720K</td><td>2</td><td>80</td><td>9</td></tr>
                <tr><td>800K</td><td>2</td><td>80</td><td>10</td></tr>
                <tr><td>880K</td><td>2</td><td>80</td><td>11</td></tr>
                <tr><td>1.44M</td><td>2</td><td>80</td><td>18</td></tr>
              </tbody>
            </table></div>
            <p>Every double-density row may also be written with 81, 82 or 83 tracks. Formatting past track 79 is what a duplicator does to fit more on a disk, and most drives read it, so the extra tracks are offered when you create an image and are honoured when one is opened. A single-sided image is exactly half of the matching double-sided one. Two PC 5.25-inch geometries, 40 tracks of 9 sectors on one or two sides, are read as well, for disks written on a PC drive. Every floppy exports as <code>.st</code>, whatever its side count.</p>
            <div class="help-warning"><strong>Image size alone does not identify the geometry.</strong> 368,640 bytes is a single-sided ST disk of 80 tracks with 9 sectors, and it is equally a double-sided PC disk of 40 tracks with 9 sectors. Guessing wrong reads the right bytes in the wrong order and produces a file list that looks almost plausible. Atari File Forge therefore does not guess.</div>
            <div class="help-task">
              <h4>How the geometry is actually decided</h4>
              <ol>
                <li>The first sector of the image is read as a BIOS parameter block. Four of its fields settle the shape: bytes per sector at offset <code>$0B</code>, total sectors at <code>$13</code>, sectors per track at <code>$18</code> and sides at <code>$1A</code>. All four are stored little-endian, which is why the hex inspector always shows both byte orders.</li>
                <li>The block is rejected outright if the sector size is not 512, the side count is not 1 or 2, the sectors per track fall outside 1 to 36, the total is zero or does not divide by sectors times sides, or the resulting track count falls outside 1 to 255.</li>
                <li>A surviving block is believed only when the geometry it describes is exactly the length of the file. That rule matters: a parameter block copied from a different disk describes a real geometry that is not this disk's, and it is ignored rather than trusted.</li>
                <li>A believed block that names a shape not in the table above is still used. It is presented as the shape the boot sector declares, because on this platform the boot sector is the disk's own word on the matter.</li>
                <li>When no block survives, the geometry is derived from the file length, and only when that length names exactly one shape. Where it names more than one, the candidates are listed and no filing system is mounted.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>A disk whose parameter block is nonsense is still readable</h4>
              <ol>
                <li>Games routinely overwrite the parameter block with their own loader, because the machine never needs it: the boot sector is executed, and the loader reads sectors by number. Such a disk has no filing system at all.</li>
                <li>Atari File Forge opens it as bytes. The pane shows the track and sector map rather than a file list, and every sector is readable, exportable and editable through the hex editor.</li>
                <li>The analysis report names the fields that disagreed and what a plausible value would have been. Nothing is repaired automatically, because the values sitting in those bytes may be part of the loader.</li>
                <li>Convert such a disk to HFE or SCP, deploy it to a Gotek, or write it to a real floppy, and it still works. What you cannot do is browse it as files, because there are none.</li>
              </ol>
            </div>
            <div class="help-note"><strong>The executable boot sector:</strong> the ST executes the boot sector only when the 16-bit words of the sector sum to <code>$1234</code>. The pane reports whether the sector sums to that value, so you can tell an ordinary data disk from a bootable one. Saving does not adjust the sum unless you ask for it, because changing a byte to restore the sum would change the loader.</div>
            <div class="help-task">
              <h4>Create and populate a floppy</h4>
              <ol>
                <li>Choose <strong>File &rarr; New &rarr; New Image</strong> and pick a geometry from the table above, then the track count.</li>
                <li>Enter a volume label. It is written into the boot sector and as the volume-label entry in the root directory.</li>
                <li>The pane opens on the root. Use <strong>File &rarr; New &rarr; New folder</strong>, <strong>File &rarr; Insert File</strong>, or drag selected files from another pane.</li>
                <li>Review shortened names and attributes before confirming each import.</li>
                <li>Use <strong>Tools &rarr; Check filesystem</strong>, optionally compact it, then select <strong>Save Image</strong> in the pane heading.</li>
              </ol>
            </div>
            <div class="help-note"><strong>To copy a whole disk into a hard disk partition:</strong> drag the disk-format badge or the open pane heading onto the destination pane. Choose a folder name, and the volume is extracted there.</div>`
    },
    {
      id: "help-msa-dim",
      title: "MSA and DIM containers",
      body: `
            <h3>MSA and DIM: packed floppy containers</h3>
            <p class="help-lead">Neither format is a filing system. Both wrap the sectors of an ordinary ST floppy, and both decode to those sectors for browsing.</p>
            <h4>MSA</h4>
            <ul>
              <li>Magic Shadow Archiver writes a ten-byte big-endian header: the identifier <code>$0E0F</code>, the sectors per track, the number of sides, and the first and last track it stored. Every track then follows as its own record with a length word in front of it.</li>
              <li>A track is stored either raw, or run-length encoded around the escape byte <code>$E5</code>. A run is encoded only when it repeats at least four times, and a literal <code>$E5</code> is always written as a run of one so it cannot be read back as an escape. A track whose encoded form would be no smaller is stored raw, and its length word says so.</li>
              <li>A track outside the stored range was never written. It is presented as an unformatted track rather than as zeroes, so an image with a short track range is not mistaken for a full disk.</li>
              <li>Bytes after the last track are reported rather than ignored quietly, because they usually mean the file was truncated or concatenated.</li>
            </ul>
            <h4>DIM</h4>
            <ul>
              <li>FastCopy Pro writes a 32-byte header beginning with <code>BB</code>, carrying the sides, sectors per track, first and last track, a density byte and a sector size. The track data follows uncompressed, so a DIM opens as quickly as a plain sector image.</li>
              <li>Only 512-byte sectors are supported. A header naming any other sector size is refused rather than read with the wrong stride.</li>
              <li>A flag in the header says whether the dump covered every sector or only the used ones. A used-sector dump is not laid out linearly, so the image's own allocation table is read and each allocated cluster is placed where it belongs. That is applied only when the table predicts exactly the length the file has; where it does not, the file is placed in order as far as it goes and the rest of the disk is left blank, and the pane says so.</li>
              <li>Only the full form is written back. An edited used-sector DIM is saved as a complete dump, because reproducing a partial one would mean deciding which sectors to omit.</li>
            </ul>
            <div class="help-task">
              <h4>Browse, edit and convert</h4>
              <ol>
                <li>Open the container in any pane. It is decoded to sectors, the parameter block in the resulting boot sector is read as it would be for a plain image, and the file list appears.</li>
                <li>Edit as you would a plain floppy. Adding, renaming and deleting all work.</li>
                <li>Select <strong>Save Image</strong> to write the container back in its own format, or <strong>File &rarr; Export as&hellip;</strong> to convert. An MSA can be exported as DIM or as a plain sector image, and the reverse conversions are offered wherever the geometry permits them.</li>
                <li>A conversion downloads as a separate file. The working image is not changed, so you can open the result in another pane and check it before using it.</li>
              </ol>
            </div>
            <div class="help-note"><strong>The packing is reproduced exactly:</strong> when an MSA is written back, each track is encoded with the same rule the original used, and the result is compared with the track it replaced. An MSA opened and saved without an edit is byte for byte the file you opened. Where an edited track would encode into a form the original writer would not have produced, the track is stored raw rather than approximated, which is what the format itself does in that case.</div>
            <div class="help-note"><strong>Geometry conflicts:</strong> the header of a container and the parameter block inside its boot sector can disagree, usually because a disk was reformatted after being dumped. The application reports both, uses the container header for extraction because that is what determines where the bytes are, and uses the parameter block for the filing system. Neither is rewritten.</div>`
    },
    {
      id: "help-stx",
      title: "Pasti STX captures",
      body: `
            <h3>Pasti STX: a capture, not a disk</h3>
            <p class="help-lead">An STX file records what the floppy controller measured while reading a disk. It is read-only in Atari File Forge, and that is a deliberate limit rather than a missing feature.</p>
            <div class="help-task">
              <h4>What is inside one</h4>
              <ol>
                <li>The file begins with <code>RSY</code> and a version word. Version 3 is the one this reader understands; anything else is named and refused rather than read on the assumption that the layout is the same.</li>
                <li>Each track is stored as the list of sector identifiers the controller found, in the order it found them, with the status byte the controller returned for each. The bits that matter are lost data, CRC error, record not found and deleted-data mark.</li>
                <li>Sector data follows separately, so a sector identifier with no data behind it is representable, which is exactly what a deliberately unreadable sector is.</li>
                <li>Where the capture was made with the timing option, the recorded read time of each sector is stored beside it. Where a track was captured whole, the raw track image is kept alongside the sectors.</li>
                <li>Where a sector read back differently on successive revolutions, the bytes that varied are recorded as fuzzy, along with the mask saying which positions were unstable.</li>
                <li>The geometry is settled by reading the boot sector out of track 0, sector 1, and falling back to the commonest sector count across the capture when that sector is itself unreadable.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Read the protection report</h4>
              <ol>
                <li>Open the capture and choose <strong>Analyse &rarr; Protection report</strong>. It gives the sectors recovered against the sectors expected, the count of unreadable sectors, the total fuzzy bytes and the number of tracks carrying evidence, then lists every track that departs from an ordinary format and says how.</li>
                <li><strong>Fuzzy bytes.</strong> Positions whose value was not stable between reads. A protection check reads the sector twice and expects the two reads to differ; a plain sector copy makes them identical and fails the check.</li>
                <li><strong>Timing.</strong> Sectors that carry recorded read times. A check that measures how long a sector takes to arrive is testing the physical layout, which a sector image does not carry.</li>
                <li><strong>Duplicate sector identifiers.</strong> Two or more sectors on one track claiming the same number. Which one the controller returns depends on where the head happened to be.</li>
                <li><strong>Missing sector identifiers.</strong> A number the loader refers to that has no address mark on the track at all. Reading it is meant to fail.</li>
                <li><strong>Non-standard sizes.</strong> Sectors of 128, 256 or 1024 bytes where 512 is expected, a sector count that is not one of the usual figures, or a long track carrying more bytes than a normal one holds.</li>
                <li><strong>Other evidence</strong> that is listed but is not itself a size problem: a raw track image kept beside the sectors, a sector whose identifier claims a different track or side from the one it sits on, and a sector written with a deleted-data mark.</li>
                <li>Each finding names its track, side and sector, so it can be checked against the loader in the hex editor.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>What you can still do with one</h4>
              <ol>
                <li>Where the capture contains a readable GEMDOS filing system, the file list is shown and files can be copied out into a writable image.</li>
                <li>Where it does not, the track and sector map and the hex view remain available, and individual sectors can be exported.</li>
                <li><strong>File &rarr; Export as&hellip;</strong> writes the recovered sectors as a plain ST image. Every finding in the protection report is listed as a loss before the export runs, because the exported disk will fail the checks the original passes.</li>
              </ol>
            </div>
            <div class="help-warning"><strong>Why writing an STX is not offered.</strong> The file records what the drive measured, not what the disk ought to contain. Writing a change back means deciding what value a fuzzy byte takes, what read time to give a sector, and what status the controller should report for a sector that was never meant to be readable. Those decisions are the protection. A capture rebuilt from them would no longer be a capture, and it would be presented as one. Export the sectors and edit those instead.</div>`
    },
    {
      id: "help-flux",
      title: "HFE and SCP flux",
      body: `
            <h3>HFE and SCP flux images: safe decoding and export</h3>
            <figure><img src="/help/hfe-create.png" alt="Create image dialog showing the HFE wrapper offered around each ST floppy geometry"><figcaption>Create a new HFE around any of the supported ST geometries. Existing supported HFE images open through the normal image picker.</figcaption></figure>
            <p>HFE stores floppy track timing and bit cells, while the GEMDOS filing system describes files inside the sectors. Atari File Forge uses the official HxCFloppyEmulator command-line converter, <code>hxcfe</code>, to decode those sectors and then opens the detected filing system. A supported HFE is not merely recognised: its decoded file list is browseable through the normal pane. Docker images and native Debian and Ubuntu packages include a pinned, architecture-native HxCFE build and its supporting libraries. No separate HxC installation is required.</p>
            <ol>
              <li>Open an HFE normally, or create an HFE-wrapped floppy from <strong>File &rarr; New &rarr; New Image</strong>.</li>
              <li>Check the opening warning. A clean HFE v1 disk is editable through the usual file tools.</li>
              <li>The revision comes from the signature: <code>HXCPICFE</code> with revision 0 is v1 and with revision 1 is v2, and <code>HXCHFEV3</code> is v3. HFE v2 and v3, weak-bit, bad-sector, protected or advanced timing images open as a clearly labelled read-only safe view. Export or drag files from them without changing their tracks.</li>
              <li>For an editable HFE, make the required changes and select <strong>Save Image</strong> in the pane heading.</li>
              <li>The application writes changed sectors into a copy of the original track layout, decodes that result, and compares every sector with the working filesystem. A mismatch blocks the download and leaves the original HFE intact.</li>
            </ol>
            <div class="help-note"><strong>What the pane shows:</strong> the format badge reads HFE, while the naming rules, geometry and capacity come from the decoded GEMDOS volume inside it. Advanced images show <strong>Read-only safe view</strong> and hide editing and compaction controls.</div>
            <div class="help-note"><strong>Transfers:</strong> any supported HFE filesystem can be opened in one pane and copied or extracted into another image. A sector image holds only sectors, so the timing, weak-bit and protection information an advanced HFE carries is deliberately omitted and reported as a destination warning.</div>
            <div class="help-task"><h4>How saving is verified</h4><ol>
              <li>The sectors are written to a file with the <code>.st</code> suffix before HxCFE is called. That suffix is how HxCFE selects its ST loader, which reads the geometry out of the parameter block; no layout is passed on the command line, so the disk describes itself exactly as it would to a machine.</li>
              <li>HxCFE encodes that file into a new HFE or SCP.</li>
              <li>HxCFE decodes the candidate output again.</li>
              <li>Atari File Forge byte-compares the decoded result with the complete working filesystem.</li>
              <li>A mismatch blocks the download, deletes the candidate and preserves the original. A successful container is added to the timestamped save package.</li>
              <li>A geometry with no flux equivalent HxCFE can write, which is the case for the PC 5.25-inch shapes, is refused before any of this begins.</li>
            </ol></div>
            <div class="help-note"><strong>Installed Linux runtime:</strong> the private HxCFE executable is <code>/opt/atari-file-forge/native/bin/hxcfe</code> and its libraries are under <code>/opt/atari-file-forge/native/lib</code>. The application launcher configures that library path automatically.</div>
            <div class="help-task"><h4>Open a Greaseweazle or SuperCard Pro SCP capture</h4><ol>
              <li>Open or drag the <code>.scp</code> file onto the workspace. The same picker works in the web and Linux desktop editions.</li>
              <li>Wait while HxCFE decodes the flux revolutions. Atari File Forge reads the parameter block in the recovered boot sector, identifies the geometry from it, then validates the complete filing system.</li>
              <li>HxCFE has a known habit of omitting the final blank sector of a disk. Where the decoded file is exactly one 512-byte sector short of a geometry the parameter block names, that one sector is restored as blank and the restoration is reported. Nothing longer is ever appended, because a file short by more than one sector is short for a different reason.</li>
              <li>Browse the normal folder hierarchy. The pane badge remains <strong>SCP</strong>, while the file rules follow the recovered filing system.</li>
              <li>Select <strong>File &rarr; Export as&hellip;</strong>, or the <strong>Export</strong> control in the pane header between <strong>Save Image</strong> and <strong>Refresh View</strong>, and choose the native sector image. The header control is greyed out when the open media has no compatible target.</li>
            </ol></div>
            <div class="help-note"><strong>Safety boundary:</strong> recognising a root directory is not enough. The application rejects a capture if the filesystem validator finds a broken allocation table, root directory or folder tree. Non-standard index timing is reported but does not block a capture whose recovered sectors validate completely.</div>
            <div class="help-note"><strong>Editing:</strong> before enabling writes, the application re-encodes the recovered sectors to SCP and decodes them again. A byte difference makes the capture read-only. Read-only captures can still be browsed, analysed, copied into another image and exported as a plain sector image.</div>`
    },
    {
      id: "help-ipf",
      title: "IPF preservation captures",
      body: `
            <h3>IPF preservation captures</h3>
            <p class="help-lead">IPF is the container the Software Preservation Society uses. Atari File Forge reads one only when the SPS decoder library is present on the machine, and that library is not bundled.</p>
            <div class="help-task">
              <h4>Why the decoder is not included</h4>
              <ol>
                <li>The decoder is <code>libcapsimage</code>. It is distributed under its own terms, which do not permit this project to redistribute it inside a Docker image or a Debian package.</li>
                <li>Everything after the decoder is built in. The flux the decoder returns is turned into sectors here, the way a WD1772 does it: the sync pattern is found, address and data marks are read, and every sector's CRC is checked before it is accepted.</li>
                <li>Build the library for your architecture, then put it in <code>~/.config/atari-file-forge/lib</code>, or set <code>ATARI_FILE_FORGE_CAPSIMAGE</code> to its full path. The application also looks in <code>/opt/atari-file-forge/native/lib</code>, <code>/usr/local/lib</code> and <code>/usr/lib</code>, and accepts the version 4 and version 5 library names.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>What happens when it is absent</h4>
              <ol>
                <li>The image still opens. It is identified as an IPF from its own signature, and the pane names the format.</li>
                <li>The pane shows a decoder-missing notice naming the library files it looked for and every path it searched, including the value of <code>ATARI_FILE_FORGE_CAPSIMAGE</code> when one is set, and points at the project's IPF guide for the build steps.</li>
                <li>No file list, no sector export and no decoded hex view are offered, because none of them can be produced without the decoder. The application says so rather than presenting an empty volume.</li>
                <li>Install the library and reopen the image. Nothing about the working session has to be rebuilt.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>With the decoder present</h4>
              <ol>
                <li>The capture decodes to sectors and browses like any other read-only image, provided it contains a GEMDOS filing system to browse.</li>
                <li>Sectors that are not 512 bytes are reported rather than written into the sector image, because a sector image has nowhere to put them. A capture from which no standard sector at all was recovered is reported as holding a format a sector image cannot represent, rather than as a damaged file.</li>
                <li>Files can be copied out into a writable image, and the recovered sectors can be exported as a plain ST image with the usual loss warning.</li>
                <li>Writing an IPF is never offered, for the same reason writing an STX is not: the container records the physical layout, and rebuilding it from edited sectors would discard the part that matters.</li>
              </ol>
            </div>`
    },
    {
      id: "help-harddisk",
      title: "Hard disks and partitions",
      body: `
            <h3>Hard disks: partition tables and the volumes they mount</h3>
            <p class="help-lead">An Atari hard disk describes itself in its first sector. Atari File Forge reads that description and shows you the drive the way the machine's driver would see it at boot.</p>
            <div class="help-task">
              <h4>The four partition tables that are read</h4>
              <ol>
                <li><strong>AHDI.</strong> Atari's own hard disk driver writes four entries into the root sector, at offset <code>$1C6</code>, each twelve bytes: a flag byte, a three-character identifier, a big-endian start sector and a big-endian length. The sector also carries the drive size, the bad-sector list and a checksum. This is what a stock machine expects to find.</li>
                <li><strong>Extended chains.</strong> An entry whose identifier is <code>XGM</code> does not hold a volume. It points at another sector holding a further set of entries, whose start sectors are relative to it, and one of those may chain on again. The chain is followed the way the Linux kernel follows it, and flattened into one list. A damaged link stops the walk and is reported at the point it broke, rather than silently truncating the drive.</li>
                <li><strong>The ICD table.</strong> ICD's driver leaves the four AHDI entries exactly where they are, so a stock machine still boots from the drive, and writes eight more into the unused space ahead of them at offset <code>$156</code>. That gives twelve partitions in one flat list, with no chain to follow.</li>
                <li><strong>PC partition tables.</strong> An image written through a PC card reader, or by an emulator, may carry an MBR at offset <code>$1BE</code> instead, ending in the <code>$55AA</code> signature. The four primary entries are read, an extended chain among them is followed, and a GEMDOS volume inside a FAT-typed entry is mounted normally.</li>
              </ol>
              <p>Which table an image has comes from its contents, never from its name. The identifier in an AHDI entry says what the partition is: <code>GEM</code> for a GEMDOS volume up to 16 MiB, <code>BGM</code> for one above that, <code>RAW</code> for a partition that is not a filing system, and <code>LNX</code> or <code>SWP</code> for Linux partitions TOS will not mount. Only <code>GEM</code> and <code>BGM</code> open as volumes; the rest are listed and left alone.</p>
            </div>
            <div class="help-task">
              <h4>Open a drive and browse a partition</h4>
              <ol>
                <li>Open the image as you would any other. The pane shows the partition table with five columns: <strong>Drive</strong>, <strong>Identifier</strong>, <strong>Size</strong>, <strong>Filing system</strong> and <strong>Boot</strong>.</li>
                <li>Nothing is mounted yet. A drive can hold partitions the running machine would refuse, and mounting one to find out is not free on a large image, so you choose the partition first.</li>
                <li>Double-click a partition to open the volume inside it. From that point everything behaves as it does on a floppy: folders open, files can be added, renamed, marked read-only, dragged and downloaded.</li>
                <li>Choose <strong>View &rarr; Return to the partition table</strong> to come back out.</li>
                <li><strong>Tools &rarr; Compact filesystem</strong> and <strong>Tools &rarr; Check filesystem</strong> act on the open partition, not on the whole drive.</li>
              </ol>
              <p>The <strong>Drive</strong> column shows the letter the partition would receive, counting from <code>C:</code>. That letter is a position in the list rather than something recorded on the disk: it is whatever the driver mounts first. A drive moved to another machine, or given a different driver, can produce different letters for the same partitions. Past the fourteenth partition there is no letter left to give, and the position is shown instead.</p>
            </div>
            <div class="help-task">
              <h4>Byte-swapped images</h4>
              <ol>
                <li>Most ST and STE IDE adapters wire the data bus the other way round from the way TOS expects. A drive attached through one holds every 16-bit word reversed, and an image taken from it is reversed too. Hatari reproduces the same case with its IDE swap option.</li>
                <li>The application detects this while identifying the image. Sector 0 is read as it stands, and then read again with its words swapped; the reading that produces a coherent partition table wins. A swap is reported, never assumed.</li>
                <li>Once detected, the image is un-swapped as it is read, so the partitions, folders and files appear the right way round with no further action from you.</li>
                <li>The working copy records that its source arrived swapped. Saving writes it back in the same byte order it came in, so the image continues to work with the adapter it came from.</li>
                <li>Use <strong>File &rarr; Export as&hellip;</strong> to write a copy in the other order, when you want to move the drive to a controller that does not swap.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Logical sector sizes</h4>
              <ol>
                <li>A GEMDOS volume does not have to use 512-byte logical sectors. 1024, 2048, 4096, 8192 and 16384 bytes are all read, and the size comes from the parameter block in the partition's own boot sector.</li>
                <li>A larger logical sector is how a large partition stays within the cluster count the filing system can address. TOS 1.x holds a cluster number in a signed 16-bit word, so a volume cannot have more than 32,766 clusters; growing the sector is what keeps a big partition under that ceiling. It is the ordinary way a 256 MiB partition is built, not an unusual case.</li>
                <li>New partitions are planned with two sectors to a cluster, and the logical sector is doubled from 512 upwards until the cluster count fits. Past 512 MiB the cluster is grown instead, because the sector has run out of room.</li>
                <li>AHDI and HDX stop at an 8 KiB logical sector. TOS 4 and third-party drivers go to 16 KiB, which is what a 512 MiB partition needs. The pane reports the size beside the partition, because it also decides how much space a small file actually consumes: one cluster, however large.</li>
                <li>A logical sector larger than 16 KiB is refused rather than read, because nothing that ships with the machine can mount it and the layout cannot be checked.</li>
              </ol>
            </div>
            <div class="help-warning"><strong>The TOS release decides the maximum partition size, and this is the limit most likely to surprise you.</strong> TOS 1.00 mounts a partition of at most 16 MiB. TOS 1.02, 1.04 and 1.62 raise that to 256 MiB. TOS 2.06, 3.06 and 4.0x allow 512 MiB. No TOS release mounts a partition over 512 MiB without a replacement such as BigDOS or MiNT. These are per-partition limits, not per-drive: a 1 GiB disk is perfectly usable on a TOS 1.04 machine as four 256 MiB partitions, and unusable as one. Atari File Forge checks a partition plan against the TOS release recorded in the applied hardware profile, and names every partition that would not mount. EmuTOS is not held to the classic limits and is not warned about.</div>
            <div class="help-task">
              <h4>Create a new drive</h4>
              <ol>
                <li>Choose <strong>File &rarr; New &rarr; New Image</strong> and pick the hard disk with a partition plan.</li>
                <li>Enter the total capacity, then choose the table kind: AHDI, AHDI with an extended chain, ICD or PC.</li>
                <li>Add partitions. Each takes a size and receives its drive letter from its position. The identifier follows the size, <code>GEM</code> up to 16 MiB and <code>BGM</code> above it, because that is the distinction the driver acts on.</li>
                <li>Choose the TOS release the drive is for. The plan is validated against its per-partition limit; against the four-entry root limit for plain AHDI, twelve for ICD and four primaries for a PC table; and, for an extended chain, against the need for one free sector in front of every partition from the fourth on to hold its chain sector.</li>
                <li>Create the image. Each partition is formatted with a boot sector, allocation tables and a root directory, and the first partition is marked bootable.</li>
              </ol>
            </div>
            <div class="help-note"><strong>The driver is not part of the image.</strong> A partition table tells a driver where the volumes are; it does not make the machine able to read them. A real ST needs its hard disk driver installed in the boot sector or the <code>AUTO</code> folder before it will mount anything. Atari File Forge builds the media and reports what is missing; it does not ship a driver.</div>`
    },
    {
      id: "help-gemdos-volume",
      title: "Bare GEMDOS volumes",
      body: `
            <h3>Bare GEMDOS volumes</h3>
            <p class="help-lead">Some images hold one filing system and nothing in front of it: no partition table, no root sector, just the volume. A partition extracted on its own is the common case, and so is an image built by a tool that only ever writes one volume.</p>
            <div class="help-task">
              <h4>How one is opened</h4>
              <ol>
                <li>The pane opens straight into the files. There is no partition table to show, so there is no partition step and no <strong>All partitions</strong> command.</li>
                <li>The geometry is taken from the parameter block in the volume's own boot sector, exactly as it is for a floppy.</li>
                <li>Where the parameter block is coherent, the volume is mounted and its cluster size, allocation-table count and root-entry count are reported.</li>
                <li>Where it is not, the image is opened as bytes, and the pane says which fields disagreed. It is not silently mounted with a guessed layout, because the wrong cluster size reads the wrong data for every file.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Give a bare volume a partition table</h4>
              <ol>
                <li>Choose <strong>File &rarr; Export as&hellip;</strong> and pick the partitioned drive.</li>
                <li>Choose the table kind and the identifier the single partition should carry.</li>
                <li>The volume is copied across unchanged, and the table is written in front of it, so the exported file is one track larger than the source.</li>
                <li>The drive then describes its own layout, which is what lets a driver mount it as <code>C:</code> without being configured for it first.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Take a partition out of a drive</h4>
              <ol>
                <li>Open the drive and enter the partition you want.</li>
                <li>Choose <strong>File &rarr; Export as&hellip;</strong> and pick the bare volume. Only the conversion that applies is listed, because converting a volume to the shape it already has is not a conversion.</li>
                <li>The open partition is written out on its own. Its boot sector goes with it, so the exported file remains self-describing.</li>
                <li>The working image is not changed either way. The conversion downloads as a separate file, which you can open in another pane to check before using it.</li>
              </ol>
            </div>
            <div class="help-note"><strong>What the file name tells you: nothing.</strong> A bare volume and a partitioned drive both turn up as <code>.img</code>, <code>.hd</code> or no extension at all. Which one a file is comes from its contents. The pane tells you which you have: a partitioned drive opens on its partition table, a bare volume opens straight into its files.</div>`
    },
    {
      id: "help-rom",
      title: "TOS and cartridge ROMs",
      body: `
            <h3>TOS and cartridge ROMs</h3>
            <p class="help-lead">A ROM is a byte image, not a filing system. The pane decodes what the image proves about itself and says plainly where the evidence stops.</p>
            <figure><img src="/help/rom-pane.png" alt="ROM pane showing the decoded TOS header, version, build date, country and the address ranges it declares"><figcaption>The main pane is a decoded inventory, not a file list. At narrow pane widths each region becomes a readable two-column card while retaining the same decoded fields.</figcaption></figure>
            <div class="help-task">
              <h4>What the TOS header proves</h4>
              <ol>
                <li>A TOS image begins with the system header. Its first word is a short branch to the reset code, and the header is trusted only when the reset longword at offset <code>$04</code> confirms that same target. The header is 32 bytes on TOS 1.00 and 48 bytes from TOS 1.02 on.</li>
                <li><strong>Version.</strong> The version word is decoded to the release it names: 1.00, 1.02, 1.04, 1.06, 1.62, 2.05, 2.06, 3.06, 4.00, 4.02, 4.04 and 4.92 are recognised, along with the machines each release shipped in. The raw word is shown beside the name.</li>
                <li><strong>Dates.</strong> Two dates are stored: a packed build date at offset <code>$18</code>, written as month, day and year, and a GEMDOS-format date word at <code>$1E</code>. Both are decoded, and a disagreement between them is reported rather than hidden, because it is a reliable sign of a patched image.</li>
                <li><strong>Country and video standard.</strong> One configuration word carries both. Its low bit is the field rate, decoded as PAL or NTSC, and the bits above it are the country, decoded by name from a table of over forty, including the multi-language value that a single ROM covering several countries uses.</li>
                <li><strong>Address ranges.</strong> The header declares where the operating system starts and ends, and carries the pointer to the GEM entry structure. Those are checked against the length of the image and against the base address a ROM of that size occupies: <code>$FC0000</code> for a 192 KiB ROM and <code>$E00000</code> for 256 KiB, 512 KiB and 1 MiB. A header that maps the system somewhere else for its size is reported.</li>
                <li><strong>EmuTOS.</strong> EmuTOS fills the same header and is recognised two ways: its own magic in the reserved longword at <code>$2C</code>, and its name in the first part of the image. It is then named as EmuTOS with its own version string rather than reported as an odd TOS release. Text without the magic, or the magic without a version string, is reported as an inconsistency instead of being resolved silently.</li>
                <li><strong>Vectors.</strong> The exception vectors the ROM installs are checked where the installation is an explicit write: Line-A, GEMDOS on <code>TRAP #1</code>, AES and VDI on <code>TRAP #2</code>, BIOS on <code>TRAP #13</code> and XBIOS on <code>TRAP #14</code>. A ROM that installs them through a table copy instead is reported as such, not as a ROM with missing vectors.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>What the application can prove, and what it cannot</h4>
              <ol>
                <li><strong>Proved:</strong> the header itself, as one segment running from the start of the image to the reset code, and every field in it.</li>
                <li><strong>Proved:</strong> the exact identity of the image, as a SHA-256 over the bytes. That is the only thing that confirms a title. The header names a release and a country; it does not prove the dump is unaltered.</li>
                <li><strong>Proved:</strong> the system font blocks, which describe themselves with their own headers and can be located, measured and named without guessing.</li>
                <li><strong>Not proved, and presented as one undivided segment:</strong> everything from the reset code to the end of the image. A TOS ROM records no boundary between its BIOS, XBIOS, GEMDOS, VDI, AES and desktop, so none is claimed. The segment is labelled as unproven and its evidence is stated as exactly that.</li>
                <li><strong>Not proved:</strong> whether a given range inside that segment is code or data. A run of bytes that disassembles cleanly may equally be a jump table, a font or a message.</li>
                <li><strong>Not proved:</strong> that the ROM will run on any particular board. A valid header says nothing about whether the code addresses hardware the machine has.</li>
                <li>Every decoded item names its evidence, so a field read from the header and a range inferred from reachability are never presented as the same kind of statement.</li>
              </ol>
              <div class="help-note"><strong>The identity catalogue starts nearly empty.</strong> A record is keyed by the exact SHA-256 of an image, so it is only meaningful once someone has hashed a ROM they actually hold. The catalogue that ships covers the bundled EmuTOS builds and nothing else. Add your own through <strong>ROM Workbench &rarr; Identity</strong>; those records stay on this host and are never published from it.</div>
            </div>
            <figure><img src="/help/rom-decoder.png" alt="Decoded TOS header fields, byte statistics and the proved and inferred regions listed separately"><figcaption>The decoder separates proven header fields, byte statistics and inferred regions. It opens with focus on the heading; Tab moves into the controls.</figcaption></figure>
            <figure><img src="/help/rom-command-help.png" alt="A pinned tooltip explaining a decoded ROM header field and where its value was read from"><figcaption>Field help states its source. Hover or keyboard focus shows it temporarily; select the question mark to pin it while reading.</figcaption></figure>
            <div class="help-task">
              <h4>Cartridge images</h4>
              <ol>
                <li>An ST cartridge is 128 KiB mapped at <code>$FA0000</code>, and is identified by the magic longword <code>$ABCDEF42</code> at its start. The application checks for it before decoding anything else.</li>
                <li>Behind the magic word is a chain of application headers, each holding the address of the next, the entry point, a flags word naming when the entry point is called, a time and date, and a name in the GEMDOS eight-plus-three form. The chain is followed and every entry is listed.</li>
                <li>A chain that leaves the image, or loops, stops the decode at the last good entry and is reported. Entries after the break are not shown as if they had been read.</li>
                <li>The flags word says whether an application runs before the boot sector, appears on the desktop, or is a diagnostic. That is decoded and shown, because it is the difference between a cartridge that takes over the machine and one that adds a desktop item.</li>
              </ol>
            </div>
            <div class="help-task"><h4>Open and inspect a ROM</h4><ol>
              <li>Open a <code>.rom</code>, <code>.tos</code>, <code>.img</code> or <code>.bin</code> carrying a recognised header. <code>.img</code> and <code>.bin</code> are also hard disk extensions, which is why the contents decide and not the name. For a headerless dump, choose the raw ROM override in the open dialog and give the mapped base address.</li>
              <li>A TOS image is one of four sizes: 192 KiB, 256 KiB, 512 KiB or 1 MiB. Anything else is reported as not a TOS size before its header is interpreted, because a truncated or padded dump produces a header that reads plausibly and maps nowhere.</li>
              <li>Read the inventory from left to right: the region and its offset in the image, the decoded identity, and whether that identity was read or inferred.</li>
              <li>Select the information control on a region to open its decoded view. It shows the header fields, the mapped address window, known ranges, and bounded printable strings with their offsets and mapped addresses.</li>
              <li>Printable text alone is never presented as structure. Help text, tables and machine code all contain runs of readable characters, so strings are labelled as evidence and nothing else.</li>
              <li>The decoder also reports SHA-256, CRC-32, entropy, distinct byte values, erased space, used range and identical regions. Header flags are checked against the actual entry vectors.</li>
              <li>Double-click a region to open the hex editor at its first byte. Use the image health dashboard to report a truncated image or a header the length contradicts.</li>
            </ol></div>
            <div class="help-task"><h4>Analyse and compare ROM code</h4><ol>
              <li>Choose <strong>Tools &rarr; ROM Workbench</strong>. Overview shows every decoded region, its file offset, its identity and any duplicate ranges.</li>
              <li>Review the audit findings. The application repairs only faults whose correct value is deterministic, such as a header field the image itself contradicts. An automatic undo point is made first.</li>
              <li>Open <strong>Disassembly</strong>, choose a region, the processor and the mapped origin. Auto detect follows the processor the applied hardware profile implies, and the 68000 when no profile is set.</li>
              <li>Every 68000-family processor is decoded big-endian, as the hardware reads it. Bytes that decode to no instruction remain visible as <code>DC.B</code> data.</li>
              <li>The listing annotates TRAP calls with the GEMDOS, BIOS, XBIOS, AES or VDI function they select when the function number is a proved constant, names system variables by their documented labels, and labels the hardware registers at <code>$FF8000</code> and <code>$FFFA00</code>.</li>
              <li>Save address labels under <strong>Project</strong> using <code>address = label</code>. Known regions use <code>start-end = meaning</code>. Disassemble again to apply them to the listing.</li>
              <li>To compare revisions, open the other ROM in another pane and select it under <strong>Compare</strong>. Download the guarded patch when required.</li>
              <li>Tick individual comparison ranges to export only reviewed changes. A patch is applied only when the complete source SHA-256 matches. The finished bytes must then match the stored target SHA-256 or the operation fails.</li>
              <li>Use <strong>Identify this exact ROM</strong> on Overview to add a private title, version, publisher and machine record. It is keyed by SHA-256 and scoped to the current browser owner.</li>
            </ol></div>
            <figure><img src="/help/rom-workbench-overview.png" alt="ROM Workbench Overview showing decoded regions, exact identity and audit findings"><figcaption>Overview relates decoded regions to file offsets, identity and duplicates. Repairs appear only when the fault and the replacement value are deterministic.</figcaption></figure>
            <figure><img src="/help/rom-workbench-disassembly.png" alt="ROM Workbench disassembly with TRAP calls annotated by GEMDOS, BIOS and XBIOS function name"><figcaption>Disassembly is bounded static analysis. Select processor, mapped origin, offset and byte count; saved project symbols and regions annotate later listings.</figcaption></figure>
            <div class="help-task"><h4>Split a ROM into the chip files a board takes</h4><ol>
              <li>A real board does not take one file. A 16-bit bus reads two devices at once, one supplying the even bytes and one the odd. The application knows the usual sets: a 192 KiB ROM is six 32 KiB chips in three even and odd pairs, as an ST or Mega ST takes; a 256 KiB ROM is two 128 KiB chips, even and odd, as an STE or Mega STE takes; and a 512 KiB ROM is either two 256 KiB chips or four 128 KiB chips in two pairs, as a TT or Falcon takes.</li>
              <li>Open <strong>ROM Workbench &rarr; Programmer</strong>. Choose the physical device size first. The image is padded to it, or mirrored to fill it, and the choice is stated in the report.</li>
              <li>Choose the transforms the board needs: adjacent-byte swapping, 16-bit word swapping, and any address-line swaps. Each is applied in the order shown, and the order is recorded.</li>
              <li>Choose one, two or four byte lanes. The image is then split, and each lane downloads as its own file named by its position.</li>
              <li>Keep the generated report with the chip files. It records the device size, every transform, and a checksum for each output file, so a programmer read-back can be verified against it.</li>
              <li>The socket order is not in the image and cannot be derived from it. Check the generated lane names against the board's own markings before programming anything.</li>
              <li>Programmer transforms affect only the downloaded files. The working ROM image is not changed.</li>
            </ol></div>
            <figure><img src="/help/rom-workbench-programmer.png" alt="ROM Workbench Programmer tab configured to split a TOS image into even and odd byte lanes"><figcaption>Programmer export applies padding or mirroring, byte and word transforms, address-line swaps, then physical lane splitting. Its report records a checksum per chip for programmer read-back.</figcaption></figure>
            <div class="help-task"><h4>Understand each Workbench tab</h4><ul>
              <li><strong>Overview:</strong> decoded regions, byte lanes, exact SHA-256 identity, audit and narrowly proven repairs.</li>
              <li><strong>Disassembly:</strong> 68000, 68010, 68020, 68030, 68040 or 68060 decoding with reachable-code analysis, cross-references, TRAP call annotation and project annotations.</li>
              <li><strong>Compare:</strong> contiguous revision differences and complete or selective patches guarded by source and target SHA-256.</li>
              <li><strong>Programmer:</strong> device padding or mirroring, adjacent-byte swaps, 16-bit word swaps, address-line swaps and one, two or four physical byte lanes.</li>
              <li><strong>Project:</strong> hardware notes, research, address labels and known regions stored outside the ROM bytes.</li>
              <li><strong>Emulator:</strong> Hatari, configured from the applied hardware profile. A TOS image is attached as the machine's system ROM; a cartridge image is attached to the cartridge port.</li>
            </ul></div>
            <div class="help-task"><h4>Run a configured emulator check</h4><ol>
              <li>Choose a machine in <strong>Workbench &rarr; Hardware profiles</strong>, then apply it to the ROM pane.</li>
              <li>Open <strong>ROM Workbench &rarr; Emulator</strong>. The panel identifies the machine and whether this ROM can be attached to it.</li>
              <li>A TOS image whose declared version does not match the selected machine is reported before it is attached, because a machine booted with a release it never shipped with fails in ways that look like a bad dump.</li>
            </ol></div>
            <div class="help-task"><h4>Troubleshoot a ROM</h4><ul>
              <li>If the identity or the mapped addresses look wrong, confirm the mapped base and the image length before editing bytes.</li>
              <li>If disassembly looks meaningless, check the processor, origin and offset. The range may be text, tables, compressed data, an interleaved dump or unreachable code.</li>
              <li>If a programmed device fails, verify chip size, erased value, lane order, swaps, board links and the read-back checksum against the Programmer report.</li>
              <li>Run <strong>Analyse &rarr; Image health dashboard</strong> after raw changes. Return to the checkpoint or the untouched source when the result is uncertain.</li>
            </ul></div>
            <div class="help-warning"><strong>Hardware warning:</strong> a valid header does not prove that code is safe, correctly mapped or suitable for a particular board. Make a checkpoint, retain the original dump and test in Hatari or on a spare programmable device first.</div>`
    },
    {
      id: "help-cd",
      title: "CD images",
      body: `
            <h3>CD images</h3>
            <p class="help-lead">An ISO 9660 image opens read-only. It is a source to copy from, not a volume to edit.</p>
            <div class="help-task">
              <h4>Browse a disc</h4>
              <ol>
                <li>Open the <code>.iso</code> in any pane. The primary volume descriptor is read, and the pane shows the volume identifier and the root directory.</li>
                <li>Folders open and breadcrumbs work as they do on a floppy. Sizes and recorded dates come from the directory records.</li>
                <li>A name recorded by a long-name extension is shown when the disc carries one: both the Joliet descriptor and the Rock Ridge name entry are read. Otherwise the plain ISO name is shown, including its version suffix, because that is what is actually on the disc.</li>
                <li>A disc written on an Atari can carry an extra entry holding the attributes the file had before it was mastered. Where it is present it is shown. Where it is not, the attribute cell is left empty rather than filled with an invented value that would look like a real one.</li>
                <li>The image is opened for each operation and closed again rather than being held open for the life of the pane, so a disc image on removable storage does not pin it.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Copy files off a disc</h4>
              <ol>
                <li>Open the destination in another pane: a hard disk partition, a floppy image or a bare volume.</li>
                <li>Select files or folders on the disc and drag them across, or use Copy and Paste.</li>
                <li>Review the name conversion. ISO names are longer and use characters GEMDOS does not accept, so the review is usually not empty. The usual shortening, upper-casing and collision checks apply.</li>
                <li>Attributes and datestamps are set from the destination's defaults and the recorded date, because a disc has no GEMDOS attribute byte to carry across.</li>
              </ol>
            </div>
            <div class="help-note"><strong>Editing is not offered.</strong> A disc image is written as one sequential stream with its directory records at fixed offsets. There is no free-space structure to allocate from, so a change means rebuilding the whole image, and the application does not present a rebuild as an edit. Copy what you need into writable media instead.</div>`
    },
    {
      group: "WORKFLOWS",
      id: "help-online",
      title: "Find software online",
      body: `
            <h3>Find and install software from the Online Library</h3>
            <figure><img src="/help/online-library.png" alt="Online Library showing the machine filter, missing-title filter and multi-selection controls"><figcaption>Search several Atari catalogues together, compare metadata and install one or many downloadable items.</figcaption></figure>
            <p class="help-lead">The Online Library uses the same format checks, metadata review and undo point as a file selected from your computer. A link is never treated as an installable image unless its source provides a direct supported download.</p>
            <div class="help-task"><h4>Install software into a drive or a floppy</h4><ol>
              <li>Open the destination: a partition on a hard disk, or a floppy image.</li>
              <li>Choose <strong>Library &rarr; Find software online</strong>. Its initial machine comes from the Workbench profile applied to this pane, or the remembered active profile when the pane has none. Change it when this search needs another machine, then search by title, publisher or keyword. Leave the search blank to browse the current catalogue page. Search results remain installable for one hour and survive a normal restart.</li>
              <li>Select the <strong>Title</strong>, <strong>Publisher</strong>, <strong>Year</strong> or <strong>Source</strong> heading to sort. The active heading shows &uarr; for ascending or &darr; for descending; select it again to reverse the order. Checked results stay selected while sorting.</li>
              <li>Use <strong>Not already present</strong> to hide likely matches found by volume label, or by a remembered online distribution name. The comparison ignores punctuation and the publisher suffix saved with online imports. This is a helpful duplicate check, not a checksum guarantee.</li>
              <li>The initial results contain only records whose supported media has been verified. Large indexes are checked in bounded groups. Choose <strong>Find more downloadable results</strong> until the status says every matching catalogue entry has been checked. Existing results and selections are retained.</li>
              <li>Select several downloadable results. Each one's expanded size is measured against the destination's free space before anything is written, so a batch that will not fit is reported before its first write rather than part way through.</li>
              <li>Review the title, publisher and launch action detected for each item after insertion. Every proposal carries the evidence behind it, and an ambiguous one is marked rather than written silently.</li>
              <li>During a multi-item install, <strong>Abort operation</strong> stops before the next download. The item already in progress finishes at a safe image boundary. The foreground status reports elapsed time, measured item throughput and an ETA once enough completed work exists to calculate them honestly.</li>
              <li>If an archive offers the same release as both a plain sector image and a packed container, the plain image is selected once. Installing into a blank image adopts its volume label; a short image is padded to the target's geometry only when the parameter block agrees.</li>
            </ol></div>
            <div class="help-task"><h4>Insert files or applications into an open disk</h4><ol>
              <li>Open a floppy image, a hard disk partition or a folder inside one, and choose <strong>Library &rarr; Find software online</strong>.</li>
              <li>A downloaded disk is extracted into the current folder by default. Select <strong>Create a folder</strong> to keep each disk separate. The preflight allocates distinct legal names across the complete batch and the existing destination entries, adding numeric suffixes when eight-character truncation would otherwise create a clash.</li>
              <li>Archives are unpacked before their contents are reviewed, so what you approve is the set of files that will actually be written.</li>
            </ol></div>
            <h4>Sources, availability and safety</h4><ul>
              <li>Each configured source is checked for actual downloadable media before an item is displayed, and continuation checks expose the whole matching index without opening thousands of remote pages at once.</li>
              <li>Records without a supported public download are omitted rather than listed as unavailable.</li>
              <li>A blocking compatibility report provides <strong>Change selection or import options</strong>, which returns focus to the relevant controls. The final Install action remains unavailable until a fresh report can proceed.</li>
              <li>Choose <strong>Sources&hellip;</strong> to edit a provider's URL, loading strategy, page layout, category roots, query templates, machine identifiers, validation limit and cache settings. The engine applies generic configured stages and never branches on a catalogue name. The editable JSON is stored in <code>catalog-sources.json</code>.</li>
              <li>Downloads are size-limited, cached briefly and checked for ZIP path traversal. A failed source is reported below the usable results instead of cancelling the complete search.</li>
            </ul>
            <div class="help-warning"><strong>Respect each archive and author:</strong> availability in a catalogue does not change a program's licence. Follow the source page for permissions, payment, documentation and the newest release.</div>`
    },
    {
      id: "help-transfer",
      title: "Copy between panes",
      body: `
            <h3>Copy and drag between panes</h3>
            <figure><img src="/help/workspace.png" alt="Two Atari images open side by side for drag and drop between them"><figcaption>Navigate the destination first, select one or more source items, then drag any selected row into another pane.</figcaption></figure>
            <div class="help-task">
              <h4>Cut, copy and paste</h4>
              <ol>
                <li>Select one or several source rows, then choose <strong>Edit &rarr; Cut</strong> or <strong>Edit &rarr; Copy</strong>. Ctrl/Cmd-X and Ctrl/Cmd-C do the same while the pane has focus.</li>
                <li>Navigate normally to the destination. Opening folders, partitions and other panes does not lose the pending selection.</li>
                <li>Choose <strong>Edit &rarr; Paste</strong>, or press Ctrl/Cmd-V in the destination pane. The same name, capacity and filesystem checks used by drag and drop are applied.</li>
                <li>The clipboard is single-use. Paste, cancelling a paste, pressing Escape, or starting a different modifying operation clears it. A cut is not removed from its source until its destination has been written successfully.</li>
                <li>Review the proposed names against the eight-character GEMDOS limit and its three-character extension before confirming.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Copy files or folders</h4>
              <ol>
                <li>Open the source in one pane and a writable destination in another.</li>
                <li>Navigate the destination to the exact folder required.</li>
                <li>Select one or more source files. Complete folder trees can also be selected.</li>
                <li>Drag any selected row into the destination pane.</li>
                <li>Review replacement names where the target has stricter rules, then confirm the copy.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Move items inside one image</h4>
              <ol>
                <li>Select one or more files or folders in a pane.</li>
                <li>Drag any selected row onto a destination folder row, or into another pane showing a different folder in the same image.</li>
                <li>The operation moves rather than copies. Existing destination objects are never silently replaced.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Import a whole disk into a folder</h4>
              <figure><img src="/help/image-import-preview.png" alt="Image import dialog previewing an ST disk's files with destination and child-folder controls"><figcaption>Inspect the source before writing. Direct extraction into the current folder is the default; choosing another destination and creating a child folder are independent options.</figcaption></figure>
              <ol>
                <li>Navigate to the folder that will contain the imported software.</li>
                <li>Drag a floppy image, MSA, DIM, HFE, SCP, STX or IPF from another pane; alternatively use <strong>File &rarr; Insert File</strong> and select an image from the host.</li>
                <li>Review the source preview. The current folder is selected by default; optionally tick <strong>Choose a different existing folder</strong> and browse the destination tree.</li>
                <li>Optionally tick <strong>Create a new child folder</strong> and enter its name. Leave it unticked to place the source contents directly in the selected destination.</li>
                <li>Direct extraction never overwrites an existing name. A rollback point protects the complete working image if extraction fails or is aborted.</li>
                <li>A floppy is not necessarily relocatable. Read the path-conversion warnings below before assuming a title will run from the drive you copied it to.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Copy a folder of files onto a volume</h4>
              <ol>
                <li>Open the destination volume and navigate to the folder that will hold the files.</li>
                <li>Drag a folder onto the pane, or choose <strong>File &rarr; Insert Folder &amp; Contents</strong> and select it.</li>
                <li>Read the cross-format review. It lists every proposed change before a byte is written, with each host name beside the GEMDOS name it will be stored under.</li>
                <li>Findings are the changes that lose something: a name cut to eight characters, a forbidden character replaced, a datestamp outside the range a FAT directory can hold, or two names that collide once shortened. Turning a lower-case name into an upper-case one is not a finding, because GEMDOS stores every name that way and compares without regard to case.</li>
                <li>Export the review as JSON or Markdown if you want a record of it, then continue.</li>
                <li>Choose whether to recreate the host folders under the current GEMDOS folder or place every file directly in it.</li>
                <li>A file already on the volume is left alone unless you tick <strong>Replace ordinary files that already have the same target path</strong>.</li>
              </ol>
            </div>
            <figure><img src="/help/copy-name-preflight.png" alt="Cross-format review listing each host filename beside the GEMDOS name it will be stored under"><figcaption>Nothing is written until the review has been read. Every proposed change names its source and its target; the findings beneath list only the changes that lose something.</figcaption></figure>
            <figure><img src="/help/destination-conflict.png" alt="Folder import dialog choosing between recreating the host folder tree and placing every file in the current folder"><figcaption>The host folder tree is either recreated under the current folder or ignored. A file already on the volume is never overwritten unless replacement is asked for.</figcaption></figure>
            <div class="help-task">
              <h4>Put several floppies onto a hard drive</h4>
              <ol>
                <li>A disk is not a folder of files, and copying one in as though it were loses the thing that made it a disk. Software written for a floppy is staged onto the drive instead, so that its own installer can be run against it.</li>
                <li>Open the destination partition, then insert each floppy image with <strong>File &rarr; Insert File</strong> or by dragging it onto the pane.</li>
                <li>Choose <strong>Install it onto this drive</strong>, then <strong>Stage it for installing later</strong>, and give every disk of a set the same title.</li>
                <li>Each disk lands under <code>INSTALL\\STAGE</code> on the drive itself, so it is in front of you when the drive is started, whether in Hatari or in a real machine.</li>
                <li>Come back with <strong>Tools &rarr; Staged disks</strong> to install a title into a folder of its own, or to discard it. The list is read off the drive, so a drive staged on another machine still reports what is waiting on it.</li>
              </ol>
            </div>
            <h4>Transfer behaviour at a glance</h4>
            <div class="help-table-wrap"><table class="help-table"><caption class="visually-hidden">Results of transferring supported source types between image formats</caption>
              <thead><tr><th>Source</th><th>Destination</th><th>Result</th></tr></thead>
              <tbody>
                <tr><td>File</td><td>Any GEMDOS volume</td><td>Copied with its attribute byte and datestamp</td></tr>
                <tr><td>Folder</td><td>Any GEMDOS volume</td><td>Recursive folder copy</td></tr>
                <tr><td>Floppy image, MSA, DIM, HFE, SCP, STX or IPF</td><td>Hard disk partition</td><td>Extracted into a new folder; loader paths are checked</td></tr>
                <tr><td>Several floppy images</td><td>Hard disk partition</td><td>Staged under one title, then installed into a folder of its own</td></tr>
                <tr><td>CD image</td><td>Any writable volume</td><td>Read-only source; names are converted on the way in</td></tr>
                <tr><td>Folder or file</td><td>Floppy image</td><td>Copied when the volume has the free clusters for it</td></tr>
              </tbody>
            </table></div>
            <div class="help-task">
              <h4>Convert floppy-bound paths safely for a hard disk</h4>
              <p>Software written for a floppy names its files through the drive they came in, as <code>A:\\GAME.PRG</code>. That reference is correct in a drive and wrong the moment the software is copied to a hard disk, because <code>A:</code> is then empty or holds a different disk.</p>
              <ol>
                <li>Import a floppy image into a folder on a hard disk in the usual way.</li>
                <li>Readable desktop configuration files and batch-style launchers have their <code>A:</code> and <code>B:</code> references rewritten as paths relative to the folder the software now lives in.</li>
                <li>Atari File Forge starts from the launcher the desktop configuration names, follows the target it names, and checks only those reachable files. Documentation and data files are not treated as launchers.</li>
                <li>A reference is rewritten only when exactly one file in the volume carries that name. Anything ambiguous is left alone and reported, because a wrong repair is worse than none.</li>
                <li>The replacement is padded with spaces to the length it replaced, so the file's size and every offset after it are unchanged.</li>
                <li>A replacement longer than the reference it replaces is refused, because lengthening the file would move every byte after it.</li>
                <li>A persistent image warning names the source image, the affected file, the old path and the replacement.</li>
                <li>A program that opens a drive by number, or reads sectors directly, cannot be repaired this way and is reported instead. Those titles should stay as floppy images.</li>
                <li>Test the imported program on its intended hardware before saving the final image. A static check cannot prove every self-modifying or dynamically constructed loader.</li>
              </ol>
              <div class="help-warning"><strong>Existing imports are not silently rewritten:</strong> compatibility analysis runs while files are copied in. To repair a folder imported with an older version, delete that folder and import its source image again. If the existing folder is populated, choose Replace only after confirming it is the correct target.</div>
            </div>`
    },
    {
      id: "help-install",
      title: "Prepare a drive and install",
      body: `
            <h3>Prepare a drive and install software onto it</h3>
            <p class="help-lead">Copying a game disk into a hard disk image gives you the files. It does not give you something that runs: the title still expects <code>A:</code>, and the drive still has no driver to mount it with.</p>
            <div class="help-task">
              <h4>Make the drive bootable</h4>
              <ol>
                <li>Open the drive on its partition table and choose <strong>Tools &rarr; Prepare drive</strong>. It reports what a real machine still needs: a driver, a boot sector that loads it, and an <code>AUTO</code> folder on the boot partition.</li>
                <li>Atari File Forge does not ship a hard disk driver and cannot fetch one. Supply the driver you own and are licensed to use, and it is written to the boot partition and, where the driver expects it, into the boot sector.</li>
                <li>AHDI and ICD Pro keep their boot loaders inside their own installers. Open a drive that driver has already prepared in the other pane and choose it under <strong>Boot loader</strong>: its root-sector and boot-sector loaders are copied, this drive keeps its own partition table and parameter block, and the prepared partition becomes the one that boots. That is what a machine running its original TOS ROM needs to find the driver.</li>
                <li>The <code>AUTO</code> folder runs before the desktop appears, in directory order, so the order programs were written into it is the order they run. The dialog lists that order and lets you change it, because a driver placed after the program that uses it never helps.</li>
                <li>A desktop configuration file is written for the drive, named for the TOS release in the applied profile: <code>DESKTOP.INF</code>, in TOS 1.x's own spelling, for TOS 1.x, and <code>NEWDESK.INF</code> for TOS 2.05 and later. TOS 1.x cannot put a program on the desktop itself, so an installed program is opened from its folder there.</li>
                <li>Every step takes a checkpoint before it writes, and each one reports what it changed.</li>
              </ol>
              <figure><img src="/help/drive-install.png" alt="Prepare drive dialog listing the boot sector, driver, AUTO folder order and desktop configuration file"><figcaption>Each requirement is listed with what the drive currently has and what will be written. Supplying a driver is a deliberate step; nothing is downloaded.</figcaption></figure>
            </div>
            <div class="help-task">
              <h4>Stage a set for installing later</h4>
              <ol>
                <li>The default, and usually the right answer for a multi-disk set. Each disk is extracted into a staging folder on the drive you are building, named after the title, and later disks merge into the same tree.</li>
                <li>The disks go onto the target image, not into a folder on this computer. That is the point: boot the drive in Hatari, or put it in a real machine, and the material is already there to finish the install with.</li>
                <li>Nothing is emulated, downloaded or guessed at, so this always works and always works quickly.</li>
                <li>Where two disks carry the same path with different contents, the first is kept and the later one is filed separately. A set is never reduced to whichever disk you staged last.</li>
                <li>Attributes and datestamps are written onto the volume with the files, because a GEMDOS directory entry has somewhere to put them.</li>
                <li>Finish the install here when the set is complete, or run the title's own installer against the staging folder on the machine itself.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Run the disk's own installer</h4>
              <ol>
                <li>For productivity software, which asks which folder, which language and which screen mode. No tool can answer those for you.</li>
                <li>Hatari boots this drive with the disk already in <code>A:</code> and hands you the keyboard. Two drives can be attached at once, so a swap is a menu choice rather than a restart.</li>
                <li>The drive is attached whole, so the installer sees the partitions you actually built. That means the drive needs its driver in place, and the machine needs a TOS ROM.</li>
                <li>Supply a TOS ROM for the release you are targeting. When you have not, the bundled EmuTOS is used instead, so the emulator always starts. EmuTOS is not TOS, and software that depends on a particular TOS release may behave differently under it; the pane says which one booted.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Finish a staged set later</h4>
              <ol>
                <li>Open the partition holding the staged disks, then choose <strong>Tools &rarr; Staged installations</strong>. The list is read off that drive, so a drive built on another machine still reports what is waiting on it.</li>
                <li>Select <strong>Install here</strong>. The title is moved out of the staging folder into the one you name, keeping the attributes and datestamps it already has.</li>
                <li>Any file that differed between two disks is named, so a set that needed a judgement call says so rather than looking complete.</li>
                <li>Discarding a title deletes the staged copies from the drive. The original disk images are untouched, so the set can be staged again.</li>
              </ol>
              <figure><img src="/help/staged-installations.png" alt="Staged installations dialog listing one waiting title, its disks and the folder it occupies on the drive"><figcaption>The staging folder is on the drive itself, so the same list appears whether you open the image here or boot it. Installing moves the title into the folder named above; discarding removes only the staged copies.</figcaption></figure>
            </div>
            <div class="help-note"><strong>Undo:</strong> staging a disk, installing a staged title, preparing a drive and writing a desktop configuration file each take a checkpoint before they run, because each one writes to a volume.</div>`
    },
    {
      id: "help-maintenance",
      title: "Check and compact",
      body: `
            <h3>Check, compact and monitor operations</h3>
            <div class="help-task">
              <h4>Check a filesystem</h4>
              <ol>
                <li>Open the volume you want to inspect. On a hard disk, open the partition first.</li>
                <li>Choose <strong>Tools &rarr; Check filesystem</strong>.</li>
                <li>Wait for the result. A structural error is reported without changing the working image.</li>
              </ol>
              <p>The check compares the two allocation tables against each other, follows every cluster chain to its end, looks for clusters claimed by two files and for clusters claimed by none, and validates each directory entry's name, attribute byte, datestamp and starting cluster. It reports; it does not repair.</p>
            </div>
            <div class="help-task">
              <h4>Compact a filesystem</h4>
              <ol>
                <li>Create a named checkpoint first if the current working state is important.</li>
                <li>Choose <strong>Tools &rarr; Compact filesystem</strong>.</li>
                <li>Optionally list paths that should be placed first, such as <code>AUTO\\HDDRIVER.PRG</code>.</li>
                <li>Confirm. Files are rewritten into contiguous clusters and free space is consolidated.</li>
                <li>Run Check filesystem afterwards, then save the compacted image.</li>
              </ol>
              <p>Compaction matters more on a floppy than on a hard disk. A fragmented file on an 11-sector disk costs a seek per fragment, and a loader that reads a large file in one pass is measurably slower for it.</p>
            </div>
            <h4>Progress, abort and retry</h4>
            <ul>
              <li>Creative and destructive controls disable as soon as an operation starts, preventing duplicate clicks.</li>
              <li>The foreground dialog reports the current phase, disk or file and completed count. Error details appear in the same foreground dialog.</li>
              <li><strong>Abort operation</strong> requests a stop at the next safe boundary. The current low-level filesystem write may need to finish first.</li>
              <li>Completed items in a bulk-copy dialog remain recorded. Use its retry path to continue with the remaining items.</li>
              <li>Do not close the browser or container during a write. A normal page refresh keeps active server sessions, but the pane should be refreshed before retrying an interrupted action.</li>
            </ul>`
    },
    {
      id: "help-hex-editor",
      title: "Raw image hex editor",
      body: `
            <h3>Raw image hex editor</h3>
            <p class="help-lead">Use the raw editor for deliberate low-level repairs and experiments. It works over the current pane without loading a complete hard disk image into the browser.</p>
            <figure><img src="/help/hex-editor.png" alt="Raw image hex editor showing offset, byte, ASCII and decoded value views over a boot sector"><figcaption>The editor overlays only its source pane. Other panes remain visible for reference, while the selected image is protected from other pane actions until the editor closes.</figcaption></figure>
            <div class="help-warning"><strong>Important:</strong> raw edits bypass the filing system, the partition table and every container rule. A plausible-looking byte change can destroy a directory, an allocation table or the geometry the whole image depends on. Create a named checkpoint first when the current state matters.</div>
            <div class="help-task"><h4>Inspect and navigate raw bytes</h4><ol>
              <li>Open <strong>Tools &rarr; Hex editor</strong> in the relevant pane. It is available at a drive's partition table as well as inside normal filesystem views.</li>
              <li>Use first, previous, next and last page, or enter a hexadecimal offset in <strong>Go to offset</strong>. Append <code>d</code> to enter a decimal address.</li>
              <li>Choose a 128, 256, 512 or 1,024-byte page. Only that range is fetched, even for a multi-gigabyte image.</li>
              <li>Select a hex or ASCII cell. The inspector shows unsigned 8, 16 and 32-bit values in little and big-endian order. A 68000 reads words big-endian; the boot sector's parameter block stores several of its fields little-endian, so both are always shown.</li>
              <li>Open <strong>Analyse</strong> to compare the current bytes with a local binary. Differing bytes are marked in the grid, the inspector reports byte and size differences, and <strong>Next difference</strong> navigates through them.</li>
              <li>Select a structure template to decode a boot sector and its parameter block, an AHDI or ICD root sector, a PC partition table, a directory entry, an allocation-table entry, a TOS system header, a cartridge application header, an MSA header and track record, a DIM header, or a generic value. Automatic mode recognises safe signatures; a template is an interpretation only and never changes bytes.</li>
            </ol></div>
            <div class="help-task"><h4>Search, select and edit</h4><ol>
              <li>Search for hexadecimal byte pairs such as <code>60 1A</code>, or switch the search to text. Find previous and Find next can wrap around the image. Find and Replace selects the complete matched range and stages a same-length replacement; it cannot insert or remove raw bytes.</li>
              <li>Click a byte, Shift-click another byte, or hold Shift while using the arrow keys to select a range.</li>
              <li>Choose HEX or ASCII mode, then type to replace bytes. You can also paste, fill the selection with one byte, copy as hex or text, or revert selected edits.</li>
              <li>Undo and redo affect staged editor changes only. The staged-change list shows the original and replacement value at every changed offset and can jump back to it.</li>
              <li>Use Ctrl/Cmd-S to write, Ctrl/Cmd-Z or Ctrl/Cmd-Y for undo or redo, Ctrl/Cmd-F to search, Ctrl/Cmd-H for replacement, Ctrl/Cmd-G to go to an offset, and Escape to close.</li>
            </ol></div>
            <div class="help-task"><h4>Write or close safely</h4><ol>
              <li>Select <strong>Write changes</strong>. Read the <strong>This is dangerous. Are you sure?</strong> warning and confirm only if the listed byte count is expected.</li>
              <li>The server rejects the write if another action changed the image after the editor loaded it. It also rejects overlaps, out-of-range writes, resizing and an unconfirmed request.</li>
              <li>An automatic undo checkpoint is created before the fixed-size byte ranges are flushed. Cached partition, folder and export data is cleared so later views cannot reuse stale content.</li>
              <li>Closing with staged bytes offers Keep editing, Discard changes, or Review and write. A read-only capture can be inspected but not written.</li>
              <li>Refresh the pane and run <strong>Analyse &rarr; Image health dashboard</strong> after every raw write. Use Edit &rarr; Undo last change if the result is not sound.</li>
            </ol></div>`
    },
    {
      id: "help-analysis",
      title: "Workbench and analysis",
      body: `
            <h3>Workbench, analysis and the file editors</h3>
            <p class="help-lead">The Analyse menu in each pane checks the image in context. Workbench in the page header stores reusable settings and portable workspace descriptions.</p>
            <div class="help-task"><h4>Run a complete image health check</h4><ol>
              <li>Open the pane's <strong>Analyse</strong> menu and choose <strong>Image health dashboard</strong>.</li>
              <li>Read the duration warning. Large hard disk images may take several minutes. The progress view names the current partition and folder and reports elapsed time, throughput and ETA. Abort operation stops at a safe boundary.</li>
              <li>If the host or client is interrupted, reopen the same installation under the same web profile or Linux user. Recover previous session restores owner-isolated working images, while History marks an in-flight server job as interrupted instead of pretending that it completed.</li>
              <li>Review filesystem, geometry, partition-table, boot-sector, launcher, compatibility and hardware-profile findings together. A failed check expands into the individual records behind it, each showing the volume, path, exact problem and supporting evidence.</li>
              <li>Where a repair is provably safe, such as a second allocation table that disagrees with a first one the cluster chains confirm, inspect the itemised count and apply it. An automatic checkpoint is made first.</li>
              <li>Run the dashboard again after repairs. A failed launcher check remains manual, because inventing a target would be unsafe.</li>
            </ol></div>
            <figure><img src="/help/health-dashboard.png" alt="Image health dashboard with an expanded failed boot sector record"><figcaption>Each failed check includes actionable evidence. Expand it to see the volume, path, the values that disagreed and the exact problem.</figcaption></figure>
            <div class="help-task"><h4>Dry-run a change</h4><ol>
              <li>Select one or more files or folders.</li>
              <li>Choose <strong>Analyse &rarr; Dry-run selected items</strong>.</li>
              <li>Review target-name conversion, truncation and case-insensitive clashes. The dry run does not write the image.</li>
              <li>Bulk imports perform their more detailed capacity, grouping and collision plan in the copy dialog.</li>
            </ol></div>
            <div class="help-task"><h4>Inspect a file, a listing or a program</h4><ol>
              <li>Double-click a file in any filesystem pane, or select it and choose <strong>Analyse &rarr; Open selected file</strong>. Use the download arrow beside its name when you only want the original file and its metadata.</li>
              <li>A program is recognised by the <code>0x601A</code> word at the start of its header. The header's text, data and symbol-table lengths and its relocation flag are decoded and shown before a single instruction is disassembled, so a truncated or padded program is identified as such.</li>
              <li>BASIC listings open as editable source. GFA BASIC, STOS BASIC and Atari ST BASIC are recognised separately, because their tokens, line structure and vocabularies differ. A numbered listing keeps its numbers; GFA's structured forms keep their nesting.</li>
              <li><code>DESKTOP.INF</code> and its later names open in the script editor. Each record is explained: which drive and path it refers to, which window it restores, and which program a document extension is bound to.</li>
              <li>Files in the <code>AUTO</code> folder are listed in directory order, which is execution order, with each one's program header decoded. That order is the single most common reason a prepared drive does not boot.</li>
              <li>Source and disassembly windows open centred at a useful working size, then scale proportionally on smaller browser windows. They can be moved by dragging the title bar and resized from any edge or corner. Use the square title-bar control, or double-click the title bar, to maximise and restore. File and Edit menus provide Save, Save As, Export, Close, undo, redo, clipboard actions, Select All, Find and Find and Replace.</li>
              <li>The tab strip keeps several files from the mounted image open together. It retains each source draft, selection and scroll position, marks dirty tabs and warns before discarding one. <strong>Open from image&hellip;</strong> searches file names and bounded readable content, restores the result's partition and folder, and opens it as another tab.</li>
              <li>BASIC and scripts use themed syntax colours for keywords, strings, numbers, remarks, symbols and line numbers. The normal textarea remains the editable document, preserving browser undo, clipboard and input-method behaviour. Hover a highlighted command for its purpose, syntax, requirements and compatibility notes, checked against the dialect actually detected.</li>
              <li>Help interprets command names and constant operands. A <code>GEMDOS</code>, <code>BIOS</code> or <code>XBIOS</code> call in BASIC is named by the function its first argument selects, with each stack argument decoded. A word write to a hardware address is named by the register it lands on, and an odd address for a word or long write is reported, because a 68000 cannot make one.</li>
              <li>Press <strong>F1</strong> for help on the command at the caret. The editor's <strong>Help</strong> menu gives an overview of the detected language, a searchable command reference, live problems and document symbols. Problem and symbol entries jump back to their source location.</li>
              <li><strong>Edit &rarr; Find all references</strong> lists code uses of the symbol at the caret. <strong>Rename symbol</strong> changes those uses as one undoable operation while leaving strings and remarks alone. Diagnostics flag unused definitions, unclosed blocks, missing procedure bodies and unreachable-line candidates.</li>
              <li><strong>Find and Replace</strong> stays open while you work and supports match case, whole identifiers, regular expressions, selection-only scope, previous and next, one replacement, preview and Replace All. <strong>Search files in this image</strong> finds names and bounded readable content across the mounted filesystem, then opens the containing location.</li>
              <li>Press <strong>Ctrl+Space</strong> for completions from known commands, identifiers, document symbols and templates. Text and script files provide duplicate, move, join and delete line operations. Numbered BASIC disables line moves that cannot preserve line-number meaning.</li>
              <li>Refactor and Condense show the original and proposed source side by side. Changed rows are marked. Every BASIC proposal completes an exact tokenise, detokenise and retokenise check before acceptance; the review displays its line count and tokenised byte size. Nothing changes until the proposal is accepted and confirmed.</li>
              <li><strong>View &rarr; Show synchronized bytes</strong> follows the BASIC line, text caret or selected disassembly row. It shows the matching saved bytes and printable characters, with a shortcut into the full Hex editor. Unsaved source is never presented as if it had already changed the image.</li>
              <li>Binary files open as bounded 68000-family disassembly. The listing annotates every <code>TRAP</code> whose function number is a proved constant with the GEMDOS, BIOS, XBIOS, AES or VDI call it selects and the arguments on the stack; names the system variables in low memory by their documented labels; and labels reads and writes of the hardware registers at <code>$FF8000</code> and <code>$FFFA00</code>. Internal targets receive stable labels derived from proved behaviour rather than anonymous names, and the hexadecimal suffix keeps similar routines distinct. The analyser drops register assumptions at uncertain control-flow joins instead of inventing values.</li>
              <li>Every disassembly row has hover help, including condition and size variants and pseudo-operations such as <code>DC.B</code> and <code>DC.W</code>. Help combines the operation family, the exact operand and addressing form, the encoded bytes, cross-references and the analyser's contextual note.</li>
              <li>The disassembly <strong>Project</strong> menu retains notes, bookmarks, symbols, offset-bound annotations and code or data decisions outside the image bytes. Click one row or shift-click a range, then mark it as code, text, bytes, words, addresses or bitmap data. The listing is rebuilt using that decision. Every word and long region uses big-endian values, because every 68000-family processor reads them that way.</li>
              <li>The processor catalogue keeps the 68000, 68010, 68020, 68030, 68040 and 68060 instruction sets distinct, and knows whether the applied profile has a floating-point unit, so an instruction the target machine cannot run is not offered as if it could.</li>
              <li><strong>Tools &rarr; Inspect selected data</strong> presents bounded text, bytes, little-endian and big-endian words, plus a one-bit bitmap preview. <strong>Compare with saved file</strong> displays saved and current source side by side.</li>
              <li><strong>Edit and reassemble</strong> is enabled only when <code>ATARI_FILE_ASSEMBLER_COMMAND</code> contains <code>{source}</code> and <code>{output}</code>. It opens generated label-oriented assembly for review and requires confirmation before checksum-guarded replacement of the complete binary. <strong>Debug from selected address</strong> uses a configured <code>ATARI_FILE_DEBUGGER_COMMAND</code>; the return status and output are retained in project history.</li>
              <li><strong>Tools &rarr; Run&hellip; / Debug&hellip;</strong> appears in every pane whose media can be attached to the configured machine. Floppy images and containers mount directly in a drive. A hard disk is attached whole, from its partition table: the application copies the working image to a private file and attaches that, so the image you are editing is isolated from emulator writes.</li>
              <li>The one managed emulator is Hatari. It boots a TOS ROM you supply, looked for in the directory named by <code>ATARI_FILE_FORGE_TOS_DIR</code>, which defaults to <code>~/.config/atari-file-forge/tos</code>, and then in the repository's own firmware directory. The releases each machine shipped with are preferred, newest first, and UK and US builds are preferred over other languages. Nothing is copied out of those directories and nothing is written into them.</li>
              <li>When no TOS ROM for the machine is found, the bundled EmuTOS of the right size boots instead, so the emulator always starts. The pane names which firmware booted and why in plain words. EmuTOS is not TOS: software that depends on a particular release may behave differently under it.</li>
              <li>Two floppy drives can be attached at once, as <code>A:</code> and <code>B:</code>. Hatari has no CD-ROM emulation, so a CD image cannot be attached to a machine; open it in a pane and copy from it instead.</li>
              <li>The running machine appears in a live display. Click the display before typing, use Full screen when useful, and choose Stop and close to end the emulator cleanly. Errors and notices raised while an editor is open are displayed inside that editor window, above its content, so they cannot be hidden behind the modal backdrop.</li>
              <li>Editor tabs, unsaved drafts, selection and scroll position survive a refresh in bounded browser-session storage. <strong>Open from image&hellip;</strong> searches every partition of a hard disk and labels results with its drive letter and volume label.</li>
              <li>ZIP, TAR, compressed TAR, GZIP, BZIP2 and XZ files are marked as archives. Double-click one to browse its safe file and folder hierarchy in the pane; use breadcrumbs or <strong>..</strong> to move up. Double-click a member to extract it in memory and open the normal BASIC, script, text, disassembly or hex viewer. Readable members can be edited: Save verifies both hashes, rebuilds the complete container and checkpoints the outer image. Parent traversal, non-regular TAR objects, archives over 512 MiB, members over 128 MiB and catalogues reaching 20,000 entries are rejected rather than processed without a safe bound.</li>
              <li>Use <strong>Tools &rarr; Open raw bytes in Hex</strong> from any file viewer when the automatic interpretation is uncertain. File saves keep the entry's attribute byte and datestamp, reject stale edits and create an undo checkpoint.</li>
              <li>Open one BASIC or machine-code file and choose <strong>Tools &rarr; Find cheat candidates</strong> inside its editor for a read-only report. On a wide editor the report docks on the right at full listing height and scrolls independently; narrow windows place it below the code. Select a candidate to centre and highlight its BASIC line or decoded address. BASIC requires corroboration between semantic state, plausible initialisation, updates, terminal tests and gameplay outcomes. Machine code joins initialisation, access to the same storage, updates, forward terminal branches and saved labels. Unexplained writes, opaque countdowns, backward decrement loops, hardware registers and likely copy, clear, scan or delay counters are suppressed. Packed or runtime-generated payloads are identified explicitly when static analysis cannot reach the final game code. For a selected machine-code result with an exact offset, <strong>Prepare guarded patch</strong> records the complete source hash, guarded bytes, hardware profile, two tester-supplied emulator observations, rationale, author and rollback instructions. Apply verifies the hash and bytes again and creates an automatic checkpoint. The host-private library matches exact files, never titles.</li>
            </ol></div>
            <figure><img src="/help/file-editor-script.png" alt="Script editor showing a real DESKTOP.INF with each record explained"><figcaption>Desktop configuration records keep their order and their exact syntax. Save keeps the entry's attribute byte and datestamp.</figcaption></figure>
            <figure><img src="/help/file-editor-basic.png" alt="GFA BASIC editor showing a tokenised listing with syntax colour and folding controls"><figcaption>A tokenised listing opens as editable source. Folding and visual indentation do not alter the saved program.</figcaption></figure>
            <figure><img src="/help/file-editor-disassembly.png" alt="Annotated 68000 disassembly with a TRAP call named as a GEMDOS function"><figcaption>Programs open as bounded 68000-family disassembly. TRAP calls, system variables and hardware registers are named beside the instruction, and the original bytes remain available through Hex.</figcaption></figure>
            <div class="help-task"><h4>Audit a collection</h4><ol>
              <li>Choose <strong>Collection</strong> in the application header, or <strong>Library &rarr; Private collection</strong> in a pane, to open the persistent catalogue. Add an open image with an optional SD-card label, NAS path or physical location and its target machines. The web edition stores complete manifests and hashes in origin-scoped IndexedDB. The Linux desktop edition uses an atomic, mode-0600 XDG client-state file. Neither catalogue contains image bytes.</li>
              <li>An indexed image is marked <strong>Refresh needed</strong> when its working revision changes. Choose <strong>Refresh indexed open images</strong> to replace matching manifests only after each scan succeeds. Exact-content, normalised-title and wanted-title reports include indexed images that are no longer open.</li>
              <li><strong>Export report</strong> downloads the current findings. <strong>Back up database</strong> retains complete versioned records and the wanted list; Import can merge or replace after bounded validation. Remove selected and Clear catalogue affect only this host's index, not images or recoverable sessions.</li>
              <li>Choose <strong>Search</strong> in the application header to search every distinct open image with one query. It matches file names, attributes, datestamps, bounded BASIC or script text, useful printable strings in programs and ROM images, recognised volume labels, publishers and launch actions, and ROM Workbench symbols, regions and notes. An 8 to 64 digit SHA-256 prefix finds exact file content and displays the complete digest. Results identify their pane, image and path. Selecting one restores and raises its pane, navigates to the containing location and opens the file.</li>
              <li><strong>Analyse &rarr; Find duplicates / variants</strong> groups byte-identical content by SHA-256 and likely variants by normalised volume label or path. It compares folder names, catalogued file content and whole volumes, so the same game installed under two different names is still found.</li>
              <li>Duplicate records are listed by title, volume and path. Select records directly using the checkbox on each result row. Equivalent groups compare names, attributes, sizes and SHA-256 file hashes. Whole-volume matches remain available as the strongest disk-level check.</li>
              <li>A compilation receives an extra warning listing the other titles it holds, so deleting it is a deliberate choice rather than an accident.</li>
              <li><strong>Export collection manifest</strong> downloads CSV or JSON containing partitions, files, metadata and checksums.</li>
              <li><strong>Compare with open image</strong> matches two manifests by path, partition or ROM region. It separates additions, removals, proven renames or moves, changed bytes and metadata-only edits. A rename is reported only when content, size and filesystem context identify one unique pair; ambiguous duplicate files remain separate additions and removals.</li>
              <li>For matching layouts, <strong>Download patch</strong> creates an <code>.affpatch.zip</code> containing the reviewed operation plan and only changed payloads. Tick changes to export a selective patch or leave every box clear for the complete comparison. <strong>Analyse &rarr; Apply guarded patch</strong> first performs a read-only preflight against the exact base fingerprint and verifies every payload. Apply remains disabled until verification succeeds. Applying creates an automatic checkpoint, repeats validation before writing and checks the complete candidate fingerprint afterwards. Abort during application restores that checkpoint. Stale, corrupt and wrong-format patches are rejected and failed applications roll back.</li>
              <li><strong>Analyse &rarr; Dry-run selected items</strong> creates a versioned compatibility report without writing. Each row records its proposed target name, metadata and any name or folder conversion or loss. Export the result as JSON or Markdown. A report without blocking findings can be kept with the working image; the next saved ZIP includes its canonical JSON and Markdown below <code>Compatibility/</code>.</li>
            </ol></div>
            <figure><img src="/help/private-collection.png" alt="Private collection catalogue showing an indexed ST floppy image, its location and target machines"><figcaption>The host-private catalogue remains searchable after an image is closed. Locations are descriptive and the database stores manifests rather than image bytes.</figcaption></figure>
            <figure><img src="/help/duplicate-check.png" alt="Duplicate review showing selectable records and equivalent disk content"><figcaption>The duplicate command lives only in Analyse. Tick the exact records to review; nothing is deleted unless the separate final review says so.</figcaption></figure>
            <div class="help-task"><h4>Hardware profiles and import recipes</h4><ol>
              <li>Choose <strong>Workbench &rarr; Hardware profiles</strong>. The base machines are the Atari 520ST and 1040ST, the Mega ST, the 520STE and 1040STE, the Mega STE, the TT030 and the Falcon030.</li>
              <li>Select the base machine in the left column, then build its hardware in the wider right column. The groups are TOS firmware, ST RAM, TT RAM, floppy drives, mass storage, the hard disk driver, the processor and its options, the display, ports and peripherals, and software loaders. Each group has its own limit, so only one firmware and one processor can be fitted while several storage interfaces can.</li>
              <li>The list changes with the machine, and a choice that cannot coexist with another is refused with the pair named. A high-density floppy drive, for instance, is offered only on the Mega STE, TT030 and Falcon030.</li>
              <li>A profile also records the Library filter, the TOS release used for partition-size validation, the firmware the emulator boots, RAM and startup action. Hardware marked <strong>Validation only</strong> still affects analysis without pretending that Hatari implements it.</li>
              <li>Save retains the profile in this host's private state. Apply retains it too, then attaches it to every open image and makes it the active profile. The active profile becomes the default for images opened or created afterwards that have no profile of their own, and drives Online Library machine filtering. Applying a profile changes no byte of an image, so it creates no undo checkpoint.</li>
              <li>Choose <strong>Import recipes</strong> to save naming, group prefix, online metadata and compatibility choices. Saved recipes appear in the import planner.</li>
            </ol></div>
            <div class="help-task"><h4>Monitor, abort and resume jobs</h4><ol>
              <li>Choose <strong>Jobs</strong> in the header. Running, paused, failed, completed and interrupted work remains visible after its foreground dialog closes.</li>
              <li>Abort requests stop at the next safe filesystem boundary.</li>
              <li>Resumable bulk jobs retain their request, completed items and skipped items. Choose <strong>Resume</strong> to submit only the remaining items.</li>
              <li>After a container restart, an unfinished job is marked interrupted instead of disappearing. Use Resume after checking the destination pane.</li>
            </ol></div>
            <figure><img src="/help/workbench-analysis.png" alt="Atari File Forge Workbench settings beside a pane's Analyse menu"><figcaption>Workbench holds reusable settings; each pane's Analyse menu runs checks against the currently open image.</figcaption></figure>`
    },
    {
      id: "help-deployment",
      title: "Hardware deployment",
      body: `
            <h3>Build media for real hardware</h3>
            <p class="help-lead">The deployment assistant creates a checked card, USB or host-directory tree without changing the image open in the workspace.</p>
            <div class="help-task"><h4>Create a deployment package</h4><ol>
              <li>Apply the intended machine and expansions in <strong>Workbench &rarr; Hardware profiles</strong>.</li>
              <li>Open the image and choose <strong>Tools &rarr; Build hardware deployment</strong>.</li>
              <li>Choose the target. Unavailable targets stay disabled and explain the source format they need.</li>
              <li>For a Gotek, choose native file names or an indexed <code>DSKA0000</code> layout and its first index.</li>
              <li>Select <strong>Validate layout</strong>. A disposable sparse snapshot is hardware-finalised and hashed, so the checks cannot alter the live pane.</li>
              <li>Review every path, role, size, SHA-256 value, profile warning and installation step. Blocking findings disable download.</li>
              <li>Select <strong>Download deployment ZIP</strong>. If the image changed after review, validate again instead of building from a stale decision.</li>
              <li>Extract to a temporary directory, back up the known-good card or device, then merge the generated tree. Complete the read, write and reboot tests in its README before retiring the backup.</li>
            </ol></div>
            <div class="help-table-wrap"><table class="help-table"><caption class="visually-hidden">Deployment targets and the layout each one generates</caption><thead><tr><th>Target</th><th>Generated layout</th><th>Important manual step</th></tr></thead><tbody>
              <tr><td>Gotek with FlashFloppy</td><td><code>GOTEK-USB</code> holding the floppy images, plus <code>FF.CFG</code></td><td>Copy its contents to a FAT-formatted USB device</td></tr>
              <tr><td>SD card for an ACSI device</td><td><code>SD-CARD</code> with the drive image at its root</td><td>Match the partition plan to the TOS release the machine runs</td></tr>
              <tr><td>CompactFlash or IDE drive</td><td><code>CF-CARD</code> with the drive image at its root</td><td>Confirm the adapter's byte order before writing the card</td></tr>
              <tr><td>GEMDOS drive folder</td><td><code>GEMDOS-DRIVE</code> as a host directory tree, plus a <code>hatari.cfg</code> fragment</td><td>Point Hatari's hard disk directory at the extracted folder</td></tr>
              <tr><td>ACSI hard drive</td><td><code>ACSI-DRIVE</code> with the drive image and its written steps</td><td>Install the hard disk driver you own before the drive will mount</td></tr>
            </tbody></table></div>
            <ul>
              <li>A Gotek presents floppy images, so a flux recording and a hard disk are not valid sources for it. Native mode keeps the file names; indexed mode renames them <code>DSKA0000</code> upwards from the first index you choose, and stops at <code>DSKA9999</code>.</li>
              <li>The generated <code>FF.CFG</code> sets the Shugart interface and the Atari host, with automatic display detection and indexed navigation. Edit it afterwards if your drive is wired differently.</li>
              <li>A GEMDOS drive folder is a host directory Hatari presents to the machine as a drive. Names in it are converted to real eight-plus-three upper case, and the tree is limited to 512 MiB, because that is what the machine can address through it.</li>
              <li>An ACSI or SD target and an IDE or CF target disagree about byte order, so each one states the order it wrote and warns when the source disagrees with it.</li>
              <li>The target is disabled, with the reason shown, when the applied hardware profile has no interface that could reach it. A CF target needs an IDE or CF adapter in the profile; an SD target needs one of the ACSI bridges.</li>
            </ul>
            <figure><img src="/help/hardware-deployment-assistant.png" alt="Hardware deployment assistant listing a Gotek target file, its checksum and the installation checks"><figcaption>The plan is built from the exact source revision. Its manifest and compatibility report travel with the generated media tree.</figcaption></figure>
            <div class="help-warning"><strong>A byte-swapped source stays byte-swapped.</strong> When the open image was detected as swapped, a CF or SD deployment writes it in the order the adapter expects and says so in the manifest. Moving that card to a controller that does not swap needs the other export, not the same file.</div>`
    },
    {
      id: "help-saving",
      title: "Save, close and recover",
      body: `
            <h3>Save, close and recover safely</h3>
            <div class="help-task">
              <h4>Keep your changes</h4>
              <ol>
                <li>Look for the orange changed dot in the pane heading.</li>
                <li>Select the <strong>Save Image</strong> icon in the pane heading. The progress bar consistently covers validation, checksums, catalogue generation and complete ZIP construction for every format.</li>
                <li>The ready dialog appears only when the timestamped ZIP is actually complete. The automatic browser download should start immediately; use the dialog's direct <strong>Download ZIP</strong> link if it does not appear.</li>
                <li>Any validation, checksum or archive failure remains inside the application instead of replacing the page with a raw response.</li>
                <li>Once preparation succeeds, the orange changed dot clears in every pane showing that image. It returns after the next edit. A failed save leaves the dot visible.</li>
                <li>Every save is a ZIP named with the image name and current date and time. This avoids duplicate downloads with the same name.</li>
                <li>Every ZIP contains <code>README.md</code> with checksums, target hardware, compatibility warnings, practical restore notes and a complete catalogue. Hard disk documentation includes the complete partition table, each partition's filing system, size and boot flag.</li>
                <li>An MSA, DIM or HFE is re-encoded and verified before downloading, and a container that fails its own verification blocks the download rather than shipping a broken file.</li>
                <li>Keep the original image until the edited download has been checked in Hatari or on a copy of the target media.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Recover after a refresh or interrupted download</h4>
              <ol>
                <li>Use any empty pane. If none is displayed, select <strong>Add Pane</strong>. There is no fixed pane-count limit, so close a pane only when it is no longer useful or use its <strong>Load New Image</strong> heading button to open a replacement.</li>
                <li>Select <strong>Recover previous session</strong>.</li>
                <li>Choose the retained working image. The newest session is selected first and each entry shows its name, size and last-change time.</li>
                <li>Select <strong>Recover session</strong>. Completed edits and the target-hardware profile are restored.</li>
                <li>Check the current folder, then select Save again.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Keep recovery private or clear old sessions</h4>
              <ol>
                <li>Web recovery is tied to an opaque identity kept in both a private cookie and this site's browser storage. Either copy restores the other after a restart. The Linux desktop edition instead keeps a stable mode-0600 owner ID in its XDG configuration directory. Another web profile or Linux user receives a different identity and cannot list, open or delete your sessions.</li>
                <li>In the recovery dialog, select <strong>Clear selected</strong> to delete one old working copy, or <strong>Clear all previous</strong> to delete every previous copy shown. Images currently open in any pane are protected from this list.</li>
                <li>Clearing removes only retained server working data. It never deletes the original file previously selected from your computer.</li>
                <li>Clearing both this site's cookies and browser storage removes the web identity. Deleting the desktop <code>owner-id</code> file has the same effect for the Linux application. Keep the identity while recoverable work remains important, and download finished images before clearing site data or resetting desktop configuration.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Close or discard a working image</h4>
              <ol>
                <li>Select &times; in the pane heading, or on an empty pane, to remove that whole pane from the workspace. A changed image offers Save and close, Close without saving, or Cancel. Closing only detaches the image and keeps its server-side working copy.</li>
                <li>Use <strong>Recover previous session</strong> to reopen the image with its completed changes.</li>
                <li>To remove retained storage permanently, use <strong>Clear selected</strong> in the recovery dialog and confirm the deletion.</li>
              </ol>
            </div>
            <div class="help-note"><strong>Two layers of safety:</strong> editing never writes to the source selected in your browser, and automatic undo points protect recent working-copy changes. Named checkpoints are ideal before large deletions, compaction or bulk menu work.</div>`
    },
    {
      group: "REFERENCE",
      id: "help-shortcuts",
      title: "Keyboard shortcuts",
      body: `
            <h3>Keyboard and mouse reference</h3>
            <dl>
              <dt>Click</dt><dd>Select one item.</dd>
              <dt>Ctrl/Cmd-click</dt><dd>Add or remove an item from the selection.</dd>
              <dt>Shift-click</dt><dd>Select a continuous range.</dd>
              <dt>Ctrl/Cmd-A</dt><dd>Select every usable item in the current view.</dd>
              <dt>Ctrl/Cmd-X</dt><dd>Cut the selected items for one safe paste.</dd>
              <dt>Ctrl/Cmd-C</dt><dd>Copy the selected items for one paste.</dd>
              <dt>Ctrl/Cmd-V</dt><dd>Paste into the current folder.</dd>
              <dt>Ctrl/Cmd-O</dt><dd>Open an image into the focused pane.</dd>
              <dt>Escape</dt><dd>Cancel a pending clipboard selection when no dialog is open.</dd>
              <dt>Double-click / Enter</dt><dd>Open a folder, or a partition from the partition table.</dd>
              <dt>Double-click a file</dt><dd>Open the content-aware BASIC, script, text, disassembly or hex editor.</dd>
              <dt>Delete</dt><dd>Delete the selected object after confirmation.</dd>
              <dt>Drag selected files</dt><dd>Copy them to a compatible destination.</dd>
              <dt>Alt+Left / Alt+Right on pane grip</dt><dd>Move a pane without dragging it.</dd>
              <dt>Alt+Up / Alt+Down on pane grip</dt><dd>Maximise or minimise a pane without dragging it.</dd>
              <dt>Breadcrumb</dt><dd>Jump directly to an ancestor folder.</dd>
              <dt>Refresh &#8635;</dt><dd>Reread the current view while preserving useful selection state.</dd>
              <dt>F1 in an editor</dt><dd>Help for the command at the caret.</dd>
            </dl>`
    },
    {
      id: "help-accessibility",
      title: "Accessibility and appearance",
      body: `
            <h3>Accessibility and appearance</h3>
            <p class="help-lead">The interface targets WCAG 2.2 AA in both its light theme and its complementary dark theme.</p>
            <ul>
              <li>Use the first keyboard link, <strong>Skip to workspace</strong>, to bypass the header. All buttons, menus, rows, form controls and dialogs have visible keyboard focus.</li>
              <li>Press Tab and Shift-Tab to move through controls. Enter opens the focused folder or partition. Native modal dialogs and safety warnings retain keyboard focus until they close.</li>
              <li>The <strong>Light / Dark</strong> button follows the operating-system preference on first use and remembers your choice. Both palettes meet AA text contrast, and control boundaries and focus indicators meet non-text contrast requirements.</li>
              <li>Selection, attributes, warnings, errors and progress use words, shapes or symbols as well as colour. Status and error regions are announced to screen readers.</li>
              <li>Browser zoom and narrower windows are supported. With reduced motion enabled in the operating system, non-essential transitions and animations are suppressed.</li>
            </ul>
            <div class="help-note"><strong>Theme maintenance:</strong> the palette is isolated in <code>theme.css</code>. Layout and component geometry remain in <code>styles.css</code>, so a replacement palette can be reviewed for contrast without changing the application structure.</div>`
    },
    {
      id: "help-limits",
      title: "Limits and troubleshooting",
      body: `
            <h3>Compatibility, limits and troubleshooting</h3>
            <h4>Important compatibility limits</h4>
            <ul>
              <li>The bundled engine creates and edits GEMDOS volumes on every supported floppy geometry, on hard disk partitions and on bare volumes. It reads and writes the FAT structures TOS itself uses and nothing beyond them.</li>
              <li>A GEMDOS name is upper case, at most eight characters with an optional three-character extension. The forbidden characters are <code>\\ / : * ? " &lt; &gt; | + , ; = [ ]</code> and the space. Comparison is case-insensitive within a folder.</li>
              <li>A root directory on a floppy holds a fixed number of entries, set by the boot sector. Folders below it are ordinary files and grow as long as the volume has free clusters.</li>
              <li>Pasti STX and IPF captures are read-only. Neither can be re-encoded from edited sectors without discarding what makes it a capture.</li>
              <li>IPF additionally needs the SPS decoder library, which this project cannot redistribute.</li>
              <li>HFE v2 and v3, bad-sector and advanced track images open read-only. Clean sector-based HFE v1 images can be edited and are verified again when saved.</li>
              <li>CD images are read-only. Copy files out into writable media.</li>
              <li>Metadata is preserved only where the destination has an equivalent field. A GEMDOS entry has an attribute byte and a two-second datestamp, and nothing else.</li>
              <li>A physical drive image means a byte-for-byte image file. The browser and container do not access devices such as <code>/dev/sdb</code> directly.</li>
            </ul>
            <h4>When something does not work</h4>
            <dl>
              <dt>Button is disabled</dt><dd>Select a suitable item first, or wait for the current pane operation to finish.</dd>
              <dt>Invalid filename</dt><dd>Use the prompted replacement. A GEMDOS name is upper case, at most eight characters plus a three-character extension, and excludes <code>\\ / : * ? " &lt; &gt; | + , ; = [ ]</code> and the space. Leading or trailing whitespace and control characters are rejected. The compatibility review normalises and truncates before writing, then checks case-insensitive clashes within each destination folder.</dd>
              <dt>Not enough space</dt><dd>Delete unwanted data, compact the filesystem, or create a larger destination. A small file still consumes a whole cluster, so a volume with a large logical sector runs out of space sooner than its free-byte total suggests.</dd>
              <dt>The image opens as bytes, not as files</dt><dd>Its boot sector's parameter block does not describe a filing system. That is normal for a game that boots its own loader. The analysis report names the fields that disagreed. The image is still fully usable through the hex editor, and still convertible and deployable.</dd>
              <dt>The file list looks almost right, but names are corrupt</dt><dd>The geometry is wrong for the image. Check the parameter block against the file length in the analysis report, and check whether the image is single sided when the block claims two.</dd>
              <dt>Partition too large for this machine</dt><dd>The applied hardware profile names a TOS release whose limit the partition exceeds: 16 MiB for TOS 1.00, 256 MiB for TOS 1.04, 512 MiB for TOS 2.06 and later. Split the capacity across more partitions, or target a later release.</dd>
              <dt>Every file name is two characters swapped</dt><dd>The image is byte-swapped and was not detected as such, which happens when the partition table is damaged. Use the byte-order export to write a corrected copy, then open that.</dd>
              <dt>HFE is read-only</dt><dd>The image uses HFE v2 or v3, reports bad sectors, or contains track features the sector editor cannot reproduce safely. Export its files or copy its readable sectors to another image.</dd>
              <dt>HxCFE is reported missing</dt><dd>Official Docker images and native packages include HxCFE and its supporting libraries. Reinstall the package matching the host distribution and architecture if <code>/opt/atari-file-forge/native/bin/hxcfe</code> is absent. A source checkout receives HxCFE when its Docker image or native package is built.</dd>
              <dt>IPF decoder is reported missing</dt><dd>The SPS decoder library is not bundled. Install it, then either place it where the loader already searches or set <code>ATARI_FILE_FORGE_CAPSIMAGE</code> to its full path and reopen the image.</dd>
              <dt>An STX will not save</dt><dd>It never will. Export its sectors as a plain image and edit that, accepting the protection loss the export lists.</dd>
              <dt>The emulator booted something unexpected</dt><dd>No TOS ROM was supplied for that profile, so the bundled EmuTOS was used. Supply the ROM for the release you are targeting in <strong>Workbench &rarr; Hardware profiles</strong>.</dd>
              <dt>The prepared drive does not boot on real hardware</dt><dd>Check three things in order: that a hard disk driver is present and the boot sector loads it, that the boot sector sums to <code>$1234</code>, and that the <code>AUTO</code> folder order puts the driver before whatever depends on it.</dd>
              <dt>Name collision found</dt><dd>Use the default generic naming strategy, or review every highlighted name. The check is case-insensitive and scoped to each destination parent.</dd>
              <dt>Empty disk found</dt><dd>Choose Skip and continue or Abort. A blank disk does not become an empty folder.</dd>
              <dt>Destination exists</dt><dd>An empty folder is reused silently. A populated folder offers Keep, Replace or Abort; a file is never overwritten as though it were an empty folder.</dd>
              <dt>Network error</dt><dd>Keep the dialog open, inspect its detailed stage, refresh the destination pane if necessary, then use retry. Online metadata can be entered manually.</dd>
              <dt>View appears stale</dt><dd>Select &#8635; in that pane. In a partition use All partitions, not the root breadcrumb, to return to the partition table.</dd>
              <dt>A refresh shows the start screen</dt><dd>Current owner-isolated panes and their open folders are restored automatically after a normal refresh. On the first refresh after upgrading from an older version, the newest retained working session for that owner is reopened as a bridge. Closing a pane deliberately removes it from auto-restore while retaining its recovery copy.</dd>
            </dl>
            <div class="help-note"><strong>Best practice:</strong> work from copies, create named checkpoints, download finished images, validate after large operations, and test the result before restoring it to real media.</div>`
    },
    {
      id: "help-project",
      title: "Portable projects and support",
      body: `
            <h3>Portable projects, the project and support</h3>
            <p class="help-lead">Atari File Forge is an open-source project. Its documentation covers installation, every supported media family, the file editors, ROM maintenance, firmware and release validation.</p>
            <div class="help-task"><h4>Export and restore a portable project</h4><ol>
              <li>Choose <strong>Workbench &rarr; Portable project</strong> to export the current pane windows, their geometry and stacking order, session references, paths, hardware profiles and import recipes as one file.</li>
              <li>Import it on the same retained installation to restore that working context. Theme remains a local host preference and is not carried.</li>
              <li>A portable project references sessions rather than containing image bytes, so it restores a layout, not the images themselves. Keep the saved ZIPs alongside it.</li>
              <li>In the same screen, choose an open image and select <strong>Export workflow bundle</strong> for a deterministic rebuild package. It records the earliest retained pre-change image hash, a guarded patch for every subsequent filesystem change, the active hardware profile, the accepted compatibility decisions, and the exact expected output hashes. The original image bytes are not included.</li>
              <li>Extract the bundle and follow its README. Its runner refuses a changed base, a changed patch or a rebuilt result whose hash does not match.</li>
              <li>Read-only captures and flux containers are rejected by the bundle rather than represented as safely reproducible, because a rebuild cannot reproduce what the application never decoded.</li>
            </ol></div>
            <div class="help-note"><strong>Confirm the running build:</strong> close this handbook, then choose <strong>Help &rarr; About Atari File Forge</strong>. The About dialog reports the version returned by the current server, the web or Linux desktop edition, the filesystem engine, the licence and the project links.</div>
            <div class="help-task"><h4>Choose the detailed reference</h4><ul>
              <li><a href="https://github.com/peteclarke-del/AtariFileForge/blob/main/docs/README.md" target="_blank" rel="noopener noreferrer">Documentation index</a>: a task and capability map for the complete handbook.</li>
              <li><a href="https://github.com/peteclarke-del/AtariFileForge/blob/main/README.md" target="_blank" rel="noopener noreferrer">Product and media handbook</a>: formats, restrictions, workflows, architecture, configuration and tests.</li>
              <li><a href="https://github.com/peteclarke-del/AtariFileForge/blob/main/docs/INSTALLATION.md" target="_blank" rel="noopener noreferrer">Installation and operations</a>: desktop and Raspberry Pi builds, ports, sessions, updates, backups and diagnostics.</li>
              <li><a href="https://github.com/peteclarke-del/AtariFileForge/blob/main/docs/FILE-EDITOR-GUIDE.md" target="_blank" rel="noopener noreferrer">File editor and code analysis</a>: BASIC, scripts, disassembly, archives, binary synchronisation and emulator hand-off.</li>
              <li><a href="https://github.com/peteclarke-del/AtariFileForge/blob/main/docs/ROM-GUIDE.md" target="_blank" rel="noopener noreferrer">ROM image handbook</a>: TOS headers, cartridges, decoded regions, Workbench, programmers and projects.</li>
              <li><a href="https://github.com/peteclarke-del/AtariFileForge/blob/main/docs/CLI-GUIDE.md" target="_blank" rel="noopener noreferrer">Headless CLI and deterministic recipes</a>: Docker invocation, stable JSON results, dry-runs, source identity checks and repeatable image builds.</li>
            </ul></div>
            <div class="help-task"><h4>Get the code or report a problem</h4><ol>
              <li>Visit <a href="https://github.com/peteclarke-del/AtariFileForge" target="_blank" rel="noopener noreferrer">github.com/peteclarke-del/AtariFileForge</a>.</li>
              <li>When reporting a problem, include the image format, target hardware profile, operation, visible error and whether the original image still opens correctly.</li>
              <li>Do not attach commercial disk images unless you have permission to share them. A catalogue, screenshot and exact error are often enough to start investigating.</li>
              <li>The repository and its source archives do not include the local <code>samples/</code> directory. Developers can place their own test images there without adding them to Git, <code>git archive</code> output or the Docker build context.</li>
            </ol></div>
            <div class="help-note"><strong>Saved archives are self-documenting:</strong> every downloaded ZIP contains a README with the image details, checksum, target profile, warnings and catalogue, plus a link back to the current project documentation.</div>`
    }
  ];

  function tableOfContents() {
    return SECTIONS.map(section => {
      const link = `<a href="#${section.id}">${section.title}</a>`;
      return section.group ? `<strong>${section.group}</strong>\n          ${link}` : link;
    }).join("\n          ");
  }

  function sectionMarkup() {
    return SECTIONS.map(
      section => `<section id="${section.id}">${section.body}\n          </section>`
    ).join("\n          ");
  }

  function create({ showModal, modalContent }) {
    function showHelp() {
      showModal(`
    <div class="help-guide">
      <div class="help-heading">
        <div><small>ATARI FILE FORGE HANDBOOK</small><h2>How to use Atari File Forge</h2></div>
        <p>Practical instructions for creating, editing, transferring, checking and saving Atari media images.</p>
      </div>
      <div class="help-layout">
        <nav class="help-toc" aria-label="Help topics">
          ${tableOfContents()}
        </nav>
        <div class="help-content">
          ${sectionMarkup()}
        </div>
      </div>
      <div class="modal-actions"><button class="button primary" value="cancel">Close help</button></div>
    </div>`);
      const layout = modalContent.querySelector(".help-layout");
      const content = modalContent.querySelector(".help-content");
      modalContent.querySelectorAll(".help-toc a").forEach(link => {
        link.addEventListener("click", event => {
          event.preventDefault();
          const target = modalContent.querySelector(link.getAttribute("href"));
          if (!target) return;
          const scrollHost = content.scrollHeight > content.clientHeight ? content : layout;
          const top = scrollHost.scrollTop
            + target.getBoundingClientRect().top
            - scrollHost.getBoundingClientRect().top;
          scrollHost.scrollTo({ top, behavior: "smooth" });
        });
      });
    }
    return showHelp;
  }

  window.AtariHelp = Object.freeze({ create });
})();
