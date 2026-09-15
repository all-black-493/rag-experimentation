const sourcesList = document.getElementById("sources-list");
const ingestStatus = document.getElementById("ingest-status");
const ingestProgress = document.getElementById("ingest-progress");
const urlForm = document.getElementById("url-form");
const urlInput = document.getElementById("url-input");
const urlSubmit = document.getElementById("url-submit");
const fileInput = document.getElementById("file-input");
const dropzone = document.getElementById("dropzone");
const askForm = document.getElementById("ask-form");
const questionInput = document.getElementById("question-input");
const askSubmit = document.getElementById("ask-submit");
const thread = document.getElementById("thread");

function setStatus(message, kind) {
  ingestStatus.textContent = message;
  ingestStatus.className = kind ? `status status--${kind}` : "status";
}

function chunkLabel(chunkCount) {
  return `${chunkCount} chunk${chunkCount === 1 ? "" : "s"}`;
}

// Static markup, no interpolation - safe to set as innerHTML.
const REMOVE_ICON = `
  <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor"
       stroke-width="1.5" stroke-linecap="round" aria-hidden="true" focusable="false">
    <path d="M4 4l8 8M12 4l-8 8" />
  </svg>`;

// The list is rendered from the server's answer rather than from what this page
// happened to upload, so it survives a reload and can't drift from what the
// model can actually see.
async function refreshSources() {
  try {
    renderSources(await api.listSources());
  } catch {
    // The list is a convenience; a failure here shouldn't replace the ingest
    // status message the user is currently reading.
  }
}

function renderSources(sources) {
  if (sources.length === 0) {
    const placeholder = document.createElement("li");
    placeholder.className = "empty-state";
    placeholder.dataset.placeholder = "";
    placeholder.textContent = "Nothing added yet.";
    sourcesList.replaceChildren(placeholder);
    return;
  }
  sourcesList.replaceChildren(...sources.map(buildSourceItem));
}

function buildSourceItem(source) {
  const item = document.createElement("li");
  item.className = "source-item";

  const nameEl = document.createElement("span");
  nameEl.className = "source-item__name";
  nameEl.textContent = source.source;
  nameEl.title = source.source;

  const countEl = document.createElement("span");
  countEl.className = "source-item__count";
  countEl.textContent = chunkLabel(source.chunks);

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "source-item__remove";
  removeButton.innerHTML = REMOVE_ICON;
  // Icon-only, so the label carries the meaning for screen readers - and names
  // the document, since the list holds several identical-looking buttons.
  removeButton.setAttribute("aria-label", `Remove ${source.source}`);
  removeButton.title = `Remove ${source.source}`;
  removeButton.addEventListener("click", () => removeSource(source, removeButton));

  item.append(nameEl, countEl, removeButton);
  return item;
}

async function removeSource(source, button) {
  const confirmed = window.confirm(
    `Remove "${source.source}"? Its ${chunkLabel(source.chunks)} will be deleted and ` +
      `answers will no longer draw on it.`,
  );
  if (!confirmed) return;

  button.disabled = true;
  setStatus(`Removing ${source.source}…`, "pending");
  try {
    await api.deleteSource(source.doc_id);
    await refreshSources();
    setStatus(`Removed ${source.source}.`, "success");
  } catch (error) {
    button.disabled = false;
    setStatus(error.message, "error");
  }
}

const MAX_FILES_PER_BATCH = 5;
const MAX_URLS_PER_BATCH = 3;

// Ingests a batch of items one at a time (not in parallel, so the rate limit
// and the progress status stay easy to reason about), reporting each success
// to the sources list as it lands and summarizing failures at the end rather
// than letting one bad item hide the others' results.
async function runBatchIngest(items, ingestOne, describeItem) {
  urlSubmit.disabled = true;
  fileInput.disabled = true;
  ingestProgress.hidden = false;

  const failures = [];
  let chunksTotal = 0;

  for (let i = 0; i < items.length; i += 1) {
    const label =
      items.length > 1
        ? `Indexing ${i + 1} of ${items.length}: ${describeItem(items[i])}…`
        : `Indexing ${describeItem(items[i])}…`;
    setStatus(label, "pending");

    try {
      const result = await ingestOne(items[i]);
      await refreshSources();
      chunksTotal += result.chunks_indexed;
    } catch (error) {
      failures.push({ item: describeItem(items[i]), message: error.message });
    }
  }

  ingestProgress.hidden = true;
  urlSubmit.disabled = false;
  fileInput.disabled = false;

  const succeededCount = items.length - failures.length;
  if (failures.length === 0) {
    setStatus(
      `Indexed ${succeededCount} source${succeededCount === 1 ? "" : "s"} (${chunkLabel(chunksTotal)} total).`,
      "success",
    );
  } else if (succeededCount === 0) {
    setStatus(failures[0].message, "error");
  } else {
    setStatus(
      `Indexed ${succeededCount}, ${failures.length} failed - ${failures[0].item}: ${failures[0].message}`,
      "error",
    );
  }
}

urlForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const urls = urlInput.value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (urls.length === 0) return;
  if (urls.length > MAX_URLS_PER_BATCH) {
    setStatus(`Add up to ${MAX_URLS_PER_BATCH} links at a time.`, "error");
    return;
  }
  runBatchIngest(
    urls,
    (url) => api.ingestUrl(url),
    (url) => url,
  ).then(() => urlForm.reset());
});

fileInput.addEventListener("change", () => {
  const files = Array.from(fileInput.files);
  if (files.length === 0) return;
  if (files.length > MAX_FILES_PER_BATCH) {
    setStatus(`Add up to ${MAX_FILES_PER_BATCH} files at a time.`, "error");
    fileInput.value = "";
    return;
  }
  runBatchIngest(
    files,
    (file) => api.ingestFile(file),
    (file) => file.name,
  ).then(() => {
    fileInput.value = "";
  });
});

// The label-for relationship already makes the dropzone clickable and
// keyboard-operable; these handlers only add drag-and-drop on top of it.
["dragenter", "dragover"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("dropzone--active");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dropzone--active");
  });
});

dropzone.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files[0];
  if (!file) return;
  fileInput.files = event.dataTransfer.files;
  fileInput.dispatchEvent(new Event("change"));
});

// Textareas don't grow with content on their own; keep the composer at one
// line until the question actually wraps.
questionInput.addEventListener("input", () => {
  questionInput.style.height = "auto";
  questionInput.style.height = `${questionInput.scrollHeight}px`;
});

function renderSkeleton() {
  const wrap = document.createElement("div");
  wrap.className = "skeleton";
  for (let i = 0; i < 3; i += 1) {
    const line = document.createElement("div");
    line.className = "skeleton__line";
    wrap.appendChild(line);
  }
  return wrap;
}

// Renders the answer's markdown (bold, headings, lists, code, ...) safely: marked
// parses to HTML, DOMPurify strips anything unsafe, then we walk the resulting DOM
// text nodes (skipping code/pre) to turn "[1]" markers into clickable badges. Doing
// the citation pass after sanitizing means it only ever touches text DOMPurify has
// already cleared, never the raw model output.
function renderMarkdownWithCitations(container, text) {
  container.innerHTML = DOMPurify.sanitize(marked.parse(text, { breaks: true, gfm: true }));
  insertCitationBadges(container);
}

function insertCitationBadges(container) {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (node.parentElement?.closest("code, pre")) return NodeFilter.FILTER_REJECT;
      return /\[\d+\]/.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });

  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) textNodes.push(node);

  const pattern = /\[(\d+)\]/g;
  for (const textNode of textNodes) {
    const text = textNode.nodeValue;
    const frag = document.createDocumentFragment();
    let lastIndex = 0;
    let match;
    pattern.lastIndex = 0;
    while ((match = pattern.exec(text)) !== null) {
      frag.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));

      const badge = document.createElement("button");
      badge.type = "button";
      badge.className = "citation-badge";
      badge.textContent = match[1];
      badge.dataset.citationIndex = match[1];
      frag.appendChild(badge);

      lastIndex = pattern.lastIndex;
    }
    frag.appendChild(document.createTextNode(text.slice(lastIndex)));
    textNode.replaceWith(frag);
  }
}

function citationLabel(citation) {
  return citation.page != null ? `${citation.title}, p.${citation.page}` : citation.title;
}

const OPENABLE_SOURCE_TYPES = new Set(["pdf", "web"]);

function renderCitations(citations, turnId) {
  const list = document.createElement("ul");
  list.className = "citations";
  for (const citation of citations) {
    const openable = OPENABLE_SOURCE_TYPES.has(citation.source_type);

    const item = document.createElement("li");
    item.className = openable ? "citation citation--openable" : "citation";
    item.id = `citation-${turnId}-${citation.index}`;
    if (openable) {
      item.tabIndex = 0;
      item.setAttribute("role", "button");
    }

    const index = document.createElement("span");
    index.className = "citation__index";
    index.textContent = `[${citation.index}]`;
    item.appendChild(index);

    if (citation.source_type === "web" && citation.favicon_url) {
      const favicon = document.createElement("img");
      favicon.className = "citation__favicon";
      favicon.src = citation.favicon_url;
      favicon.alt = "";
      favicon.loading = "lazy";
      favicon.width = 14;
      favicon.height = 14;
      favicon.addEventListener("error", () => favicon.remove(), { once: true });
      item.appendChild(favicon);
    }

    const label = document.createElement("span");
    label.className = "citation__label";
    label.textContent = citationLabel(citation);
    item.appendChild(label);

    const preview = renderCitationPreview(citation, item);
    if (preview) item.appendChild(preview);

    list.appendChild(item);
  }
  return list;
}

// Hover preview of the cited page (or the site's own og:image). Only revealed
// where hovering is a real gesture - see the (hover: hover) and (pointer: fine)
// guard in styles.css. On a touch screen there's no hover to reveal it, and
// tapping the citation opens the source anyway.
//
// The image is pre-rendered server-side at ingestion but fetched on first hover,
// so an answer citing five sources doesn't pull five images nobody looks at.
function renderCitationPreview(citation, item) {
  if (!citation.thumbnail_url) return null;

  const preview = document.createElement("span");
  preview.className = "citation__preview";
  preview.setAttribute("aria-hidden", "true");

  const image = document.createElement("img");
  image.alt = "";
  preview.appendChild(image);

  const load = async () => {
    try {
      // A PDF page lives under the session-scoped /files route, so it needs the
      // session header and can't go straight into src. A web og:image is public
      // and cached under an opaque key, so it can.
      image.src = citation.thumbnail_url.startsWith("/files/")
        ? await api.imageObjectUrl(citation.thumbnail_url)
        : citation.thumbnail_url;
    } catch {
      preview.remove();
    }
  };

  // once: the fetched image stays in src for any later hover.
  item.addEventListener("pointerenter", load, { once: true });
  item.addEventListener("focus", load, { once: true });

  return preview;
}

// A citation badge or list entry opens the source: a PDF citation opens the
// viewer at the cited page, a web citation opens the page in a new tab, and
// anything else falls back to scrolling to its entry in the list below.
function handleCitationActivate(citation, turnId) {
  if (!citation) return;

  if (citation.source_type === "pdf" && citation.doc_id) {
    openPdfViewer(citation);
    return;
  }

  if (citation.source_type === "web") {
    window.open(citation.source, "_blank", "noopener,noreferrer");
    return;
  }

  const target = document.getElementById(`citation-${turnId}-${citation.index}`);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.add("citation--highlight");
  setTimeout(() => target.classList.remove("citation--highlight"), 1200);
}

function wireCitationInteractions(answerBody, citations, turnId) {
  const byIndex = new Map(citations.map((citation) => [citation.index, citation]));

  answerBody.querySelectorAll(".citation-badge").forEach((badge) => {
    badge.addEventListener("click", () => {
      handleCitationActivate(byIndex.get(Number(badge.dataset.citationIndex)), turnId);
    });
  });

  answerBody.querySelectorAll(".citation--openable").forEach((item) => {
    item.dataset.index = item.querySelector(".citation__index").textContent.slice(1, -1);
    const activate = () => handleCitationActivate(byIndex.get(Number(item.dataset.index)), turnId);
    item.addEventListener("click", activate);
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activate();
      }
    });
  });
}

let turnCounter = 0;

function createTurn(question) {
  turnCounter += 1;
  const turnId = turnCounter;

  const article = document.createElement("article");
  article.className = "turn";

  const questionBlock = document.createElement("div");
  questionBlock.className = "turn__question";
  const questionLabel = document.createElement("span");
  questionLabel.className = "turn__label";
  questionLabel.textContent = "You";
  const questionText = document.createElement("p");
  questionText.textContent = question;
  questionBlock.append(questionLabel, questionText);

  const answerBlock = document.createElement("div");
  answerBlock.className = "turn__answer";
  const answerLabel = document.createElement("span");
  answerLabel.className = "turn__label";
  answerLabel.textContent = "Answer";
  const answerBody = document.createElement("div");
  answerBody.className = "answer-body";
  answerBody.appendChild(renderSkeleton());
  answerBlock.append(answerLabel, answerBody);

  article.append(questionBlock, answerBlock);

  const placeholder = thread.querySelector("[data-placeholder]");
  if (placeholder) placeholder.remove();
  thread.prepend(article);

  return { turnId, answerBlock, answerBody };
}

function renderAnswer(turn, result) {
  const isDecline = result.citations.length === 0;

  const answerBody = document.createElement("div");
  answerBody.className = isDecline ? "answer-body answer-body--decline" : "answer-body";

  if (isDecline) {
    answerBody.textContent = result.answer;
  } else {
    renderMarkdownWithCitations(answerBody, result.answer);
    answerBody.appendChild(renderCitations(result.citations, turn.turnId));
    wireCitationInteractions(answerBody, result.citations, turn.turnId);
  }

  turn.answerBlock.replaceChild(answerBody, turn.answerBody);
}

function renderAnswerError(turn, message) {
  const errorBody = document.createElement("p");
  errorBody.className = "status status--error";
  errorBody.textContent = message;
  turn.answerBlock.replaceChild(errorBody, turn.answerBody);
}

askForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;

  askSubmit.disabled = true;
  questionInput.disabled = true;
  questionInput.value = "";
  questionInput.style.height = "auto";

  const turn = createTurn(question);

  try {
    const result = await api.query(question);
    renderAnswer(turn, result);
  } catch (error) {
    renderAnswerError(turn, error.message);
  } finally {
    askSubmit.disabled = false;
    questionInput.disabled = false;
    questionInput.focus();
  }
});

// Anything indexed in an earlier visit is still queryable, so show it on load -
// otherwise the sidebar claims the session is empty while the model can see a
// dozen documents.
refreshSources();
