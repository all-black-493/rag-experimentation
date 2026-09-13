// Renders one PDF page in a native <dialog> and highlights the bounding box a
// citation quotes. Loaded lazily (PDF.js is ~1.7MB) via dynamic import, only
// once a citation with a doc_id is actually activated.
//
// PDF.js needs the native Uint8Array.toHex()/fromHex() (a recent JS engine
// addition); this polyfills it on browsers that predate it. Applied here, on
// the main thread - the worker gets its own copy via pdf.worker.shim.mjs,
// since a Worker has a separate global scope this can't reach.
if (typeof Uint8Array.prototype.toHex !== "function") {
  Uint8Array.prototype.toHex = function () {
    return Array.from(this, (b) => b.toString(16).padStart(2, "0")).join("");
  };
}
if (typeof Uint8Array.fromHex !== "function") {
  Uint8Array.fromHex = function (hex) {
    const bytes = new Uint8Array(hex.length / 2);
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
    }
    return bytes;
  };
}

let pdfjsLibPromise = null;

function loadPdfjs() {
  pdfjsLibPromise ??= import("./vendor/pdf.min.mjs").then((mod) => {
    // Root-absolute: a page-relative path resolves differently depending on
    // whether PDF.js spawns a real Worker (resolved against the page URL) or
    // falls back to its same-thread "fake worker" (resolved against
    // pdf.min.mjs's own URL inside vendor/) - a leading "/" resolves the same
    // either way.
    mod.GlobalWorkerOptions.workerSrc = "/vendor/pdf.worker.shim.mjs";
    return mod;
  });
  return pdfjsLibPromise;
}

const panel = document.getElementById("pdf-viewer");
const titleEl = document.getElementById("pdf-viewer-title");
const closeBtn = document.getElementById("pdf-viewer-close");
const toggleBtn = document.getElementById("pdf-viewer-toggle");
const canvas = document.getElementById("pdf-viewer-canvas");
const highlight = document.getElementById("pdf-viewer-highlight");
const body = document.getElementById("pdf-viewer-body");

closeBtn.addEventListener("click", () => {
  panel.hidden = true;
});

toggleBtn.addEventListener("click", () => {
  const collapsed = toggleBtn.getAttribute("aria-expanded") === "false";
  toggleBtn.setAttribute("aria-expanded", String(collapsed));
  body.hidden = !collapsed;
});

// PyMuPDF's bbox/page_width are in its own top-left-origin, y-down space -
// the same convention <canvas> uses - so the highlight is a plain scale from
// PDF points to rendered pixels, no coordinate-system flip needed.
function positionHighlight(bbox, scale) {
  const [x0, y0, x1, y1] = bbox;
  highlight.style.left = `${x0 * scale}px`;
  highlight.style.top = `${y0 * scale}px`;
  highlight.style.width = `${(x1 - x0) * scale}px`;
  highlight.style.height = `${(y1 - y0) * scale}px`;
  highlight.hidden = false;
}

async function openPdfViewer(citation) {
  titleEl.textContent = citation.page != null ? `${citation.title}, p.${citation.page}` : citation.title;
  highlight.hidden = true;
  // Activating a new citation always expands: opening a collapsed panel onto a
  // page you can't see would look like nothing happened.
  panel.hidden = false;
  body.hidden = false;
  toggleBtn.setAttribute("aria-expanded", "true");

  try {
    const pdfjsLib = await loadPdfjs();
    // A URL (not a pre-fetched buffer) lets PDF.js fetch byte ranges itself:
    // the backend serves 206s, so a citation deep in a large PDF pulls only the
    // xref plus that page rather than the whole file. disableAutoFetch stops it
    // from backfilling the remaining pages we never render - this viewer only
    // ever shows the one cited page.
    const pdf = await pdfjsLib.getDocument({
      url: api.pdfUrl(citation.doc_id),
      httpHeaders: { "X-Session-Id": getSessionId() },
      disableAutoFetch: true,
    }).promise;
    const page = await pdf.getPage(citation.page ?? 1);

    // Fit the page to the panel's content box. Measured rather than hardcoded so
    // it stays correct if the padding token or panel width changes; the extra 2
    // accounts for the canvas's own 1px border on each side, which would
    // otherwise overflow and add a horizontal scrollbar.
    const style = getComputedStyle(body);
    const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    const availableWidth = body.clientWidth - padding - 2;
    const unscaled = page.getViewport({ scale: 1 });
    const scale = Math.min(availableWidth / unscaled.width, 1.5);
    const viewport = page.getViewport({ scale });

    canvas.width = viewport.width;
    canvas.height = viewport.height;
    await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;

    if (citation.bbox) positionHighlight(citation.bbox, scale);
  } catch (error) {
    titleEl.textContent = `Couldn't load the source PDF: ${error.message}`;
  }
}
