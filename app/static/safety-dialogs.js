window.AtariSafetyDialogs = (() => {
  // A GEMDOS program carries a longword of program flags at offset $16 of
  // its 28-byte header, the field the TOS sources call _p_flags. Bit 0 asks
  // for fast load, which skips clearing the heap; bit 1 lets the program be
  // loaded into TT RAM; bit 2 lets Malloc give it TT RAM; bits 4 to 7 set
  // the memory protection mode under MiNT. The launcher scan reads the value
  // from the actual file, so a value typed in by hand is checked against it
  // before it is written.
  function create({ esc, normalisePage, trapFocus }) {
    function showFlagsWarning({ heading, body, list = "", confirmLabel }) {
      return new Promise(resolve => {
        const overlay = document.createElement("div");
        overlay.className = "page-warning-overlay";
        overlay.setAttribute("role", "alertdialog");
        overlay.setAttribute("aria-modal", "true");
        overlay.setAttribute("aria-labelledby", "page-warning-title");
        overlay.innerHTML = `<div class="page-warning-card"><span class="page-warning-icon" aria-hidden="true">!</span><h2 id="page-warning-title">${heading}</h2>${body}${list}<div class="help-warning"><strong>Risk:</strong> the wrong program flags can load code into TT RAM it cannot address, skip clearing memory the program expects to be zero, or give MiNT a protection mode that stops it running at all.</div><div class="modal-actions"><button type="button" class="button ghost" data-page-cancel>Cancel</button><button type="button" class="button primary" data-page-confirm>${confirmLabel}</button></div></div>`;
        const previouslyFocused = document.activeElement;
        const finish = result => { overlay.remove(); previouslyFocused?.focus(); resolve(result); };
        overlay.querySelector("[data-page-cancel]").onclick = () => finish(false);
        overlay.querySelector("[data-page-confirm]").onclick = () => finish(true);
        overlay.onkeydown = event => event.key === "Escape" ? finish(false) : trapFocus(overlay, event);
        document.body.append(overlay);
        overlay.querySelector("[data-page-cancel]").focus();
      });
    }

    function confirmPageOverride(defaultPage, chosenPage, subjects = []) {
      if (Array.isArray(defaultPage)) {
        const overrides = defaultPage.filter(item => item?.defaultPage && item?.chosenPage);
        if (!overrides.length) return Promise.resolve(true);
        const list = `<div class="page-warning-list">${overrides.slice(0, 8).map(item => `<span><b>${esc(item.title)}</b><small>$${esc(normalisePage(item.defaultPage))} in the file → $${esc(normalisePage(item.chosenPage))} entered</small></span>`).join("")}${overrides.length > 8 ? `<em>and ${overrides.length - 8} more…</em>` : ""}</div>`;
        return showFlagsWarning({ heading: `Use ${overrides.length} changed program flag ${overrides.length === 1 ? "value" : "values"}?`, body: "<p>These values differ from the <code>_p_flags</code> words in the program headers on the actual disk images.</p>", list, confirmLabel: "Yes, use changed values" });
      }
      if (!defaultPage || normalisePage(defaultPage) === normalisePage(chosenPage)) return Promise.resolve(true);
      const labels = Array.isArray(subjects) ? subjects.filter(Boolean) : [subjects].filter(Boolean);
      return showFlagsWarning({
        heading: "Use different program flags?",
        body: `<p>The program header in the disk image holds <strong>$${esc(normalisePage(defaultPage))}</strong> in <code>_p_flags</code>, but you entered <strong>$${esc(normalisePage(chosenPage))}</strong>.</p>${labels.length ? `<p class="page-warning-subject">${esc(labels.slice(0, 4).join(", "))}${labels.length > 4 ? ` and ${labels.length - 4} more` : ""}</p>` : ""}`,
        confirmLabel: `Yes, use $${esc(normalisePage(chosenPage))}`,
      });
    }
    return { confirmPageOverride, confirmFlagsOverride: confirmPageOverride };
  }
  return { create };
})();
