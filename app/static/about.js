(() => {
  "use strict";

  function create({ showModal, esc, context }) {
    return function showAbout() {
      const details = context();
      const host = details.host === "desktop" ? "Linux desktop application" : "Web application";
      showModal(`<div class="about-dialog">
        <header class="about-heading">
          <img src="/favicon.svg" alt="">
          <div><small>ATARI FILE IMAGE WORKSHOP</small><h2>Atari File Forge</h2><p>Version ${esc(details.version)}</p></div>
        </header>
        <p>Create, inspect, edit, convert, validate and deploy Atari media images from one shared workbench.</p>
        <dl class="about-facts">
          <dt>Edition</dt><dd>${esc(host)}</dd>
          <dt>Filesystem engine</dt><dd>${esc(details.engine)}</dd>
          <dt>Formats</dt><dd>ST, MSA, DIM and STX floppies, HFE, SCP and IPF flux, AHDI and MBR hard disks, bare GEMDOS volumes, TOS and cartridge ROMs</dd>
          <dt>Platforms</dt><dd>Atari ST, Mega ST, STE, Mega STE, TT030 and Falcon030</dd>
          <dt>Licence</dt><dd>MIT License · Copyright © 2026 Pete Clarke</dd>
        </dl>
        <nav class="about-links" aria-label="Project links">
          <a class="button small" href="https://github.com/peteclarke-del/AtariFileForge" target="_blank" rel="noopener noreferrer">Source and support</a>
          <a class="button small" href="https://github.com/peteclarke-del/AtariFileForge/releases" target="_blank" rel="noopener noreferrer">Release downloads</a>
          <a class="button small" href="https://github.com/peteclarke-del/AtariFileForge/blob/main/THIRD_PARTY_NOTICES.md" target="_blank" rel="noopener noreferrer">Third-party notices</a>
        </nav>
        <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div>
      </div>`);
    };
  }

  window.AtariAbout = Object.freeze({ create });
})();
