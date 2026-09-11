// Messages say how serious they are and are never left under a dialog.
//
// A modal dialog sits in the browser's top layer behind a blurred backdrop,
// so a message left in the page while one was open was drawn underneath the
// blur, and one raised inside a dialog vanished with it. Each kind of message
// also has its own colour: information yellow, a warning orange, an error red.
const { chromium } = require("playwright");

const target = process.env.ATARI_FILE_FORGE_URL || "http://127.0.0.1:8666";

async function onTop(page, text) {
  // The element actually drawn at the middle of the message is the message
  // itself, not a backdrop or a dialog laid over it.
  return page.evaluate(wanted => {
    const item = [...document.querySelectorAll("#toasts .toast")].find(node => node.textContent.includes(wanted));
    if (!item) return "missing";
    const box = item.getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + 12, box.top + box.height / 2);
    return item.contains(hit) ? "on top" : `covered by ${hit?.outerHTML.slice(0, 80)}`;
  }, text);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.goto(target, { waitUntil: "networkidle" });

    const colours = await page.evaluate(() => {
      window.AtariUI.toast("An information message", "info");
      window.AtariUI.toast("A warning message", "warning");
      window.AtariUI.toast("An error message", true);
      window.AtariUI.toast("A second error message", "error");
      const token = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      const probe = document.createElement("span");
      document.body.append(probe);
      const resolve = value => { probe.style.color = value; return getComputedStyle(probe).color; };
      const expected = {
        info: resolve(token("--yellow")),
        warning: resolve(token("--orange")),
        error: resolve(token("--danger")),
      };
      probe.remove();
      const shown = Object.fromEntries(["info", "warning", "error"].map(kind => [
        kind, getComputedStyle(document.querySelector(`#toasts .toast.${kind}`)).backgroundColor,
      ]));
      return { expected, shown };
    });
    for (const kind of ["info", "warning", "error"]) {
      if (colours.shown[kind] !== colours.expected[kind]) {
        throw new Error(`A ${kind} message is ${colours.shown[kind]}, not ${colours.expected[kind]}`);
      }
    }
    if (await page.locator("#toasts button", { hasText: "Dismiss all" }).count()) {
      throw new Error("Several errors still offer a Dismiss all button");
    }

    // An error raised before a dialog opens is still readable once it is open.
    await page.evaluate(() => {
      window.AtariUI.showModal('<h2>Dialog</h2><p>Body</p><div class="modal-actions"><button class="button" value="cancel">Close</button></div>');
    });
    await page.waitForSelector("#modal[open]");
    const before = await onTop(page, "A second error message");
    if (before !== "on top") throw new Error(`An earlier error is under the open dialog: ${before}`);

    // One raised while the dialog is open is on top too, and can be dismissed.
    await page.evaluate(() => window.AtariUI.toast("Raised inside the dialog", "warning"));
    const inside = await onTop(page, "Raised inside the dialog");
    if (inside !== "on top") throw new Error(`A message raised in a dialog is covered: ${inside}`);
    await page.locator("#toasts .toast", { hasText: "Raised inside the dialog" }).locator(".toast-dismiss").click();
    if (await page.locator("#toasts .toast", { hasText: "Raised inside the dialog" }).count()) {
      throw new Error("A warning could not be dismissed while a dialog was open");
    }

    // Closing the dialog brings the messages back out rather than losing them.
    await page.locator('#modalContent button[value="cancel"]').click();
    // The dialog's open flag clears before its close event runs, and the
    // messages move out in that event, so wait for the move itself.
    await page.waitForFunction(() => !document.querySelector("#modal").open
      && document.querySelector("#toasts").parentElement === document.body, null, { timeout: 5000 })
      .catch(() => {});
    const after = await page.evaluate(() => ({
      parent: document.querySelector("#toasts").parentElement.tagName,
      errors: document.querySelectorAll("#toasts .toast.error").length,
    }));
    if (after.parent !== "BODY" || after.errors !== 2) {
      throw new Error(`Messages were not returned to the page intact: ${JSON.stringify(after)}`);
    }
    if (await onTop(page, "An error message") !== "on top") throw new Error("An error is covered once the dialog closes");
    console.log("Notification browser regression passed");
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
