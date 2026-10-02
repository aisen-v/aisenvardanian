// Dashboard for editing the site's content. See storage.js for where it saves.

const MAX_SIZE = 2000; // long edge of uploaded photos, in px
const QUALITY = 0.86;

const $ = (id) => document.getElementById(id);
const panel = $("panel");
const statusEl = $("status");
const publishBtn = $("publish");
const store = createStore();

let content = null;
let view = { type: "settings" }; // or { type: "project", project }
const pendingUploads = new WeakMap(); // project -> [{ name, state }]
const autoSlug = new WeakSet(); // new projects whose address follows the title

// ---------- helpers ----------

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k in el && k !== "list") el[k] = v;
    else el.setAttribute(k, v);
  }
  el.append(...children.flat().filter((c) => c != null && c !== false));
  return el;
}

const pad = (i) => String(i + 1).padStart(2, "0");

function slugify(text) {
  const s = text
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return s || "project";
}

function uniqueSlug(base, except) {
  const taken = new Set(content.projects.filter((p) => p !== except).map((p) => p.slug));
  let slug = base;
  for (let i = 2; taken.has(slug); i++) slug = `${base}-${i}`;
  return slug;
}

function move(arr, from, to) {
  const [item] = arr.splice(from, 1);
  arr.splice(from < to ? to - 1 : to, 0, item);
}

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

// ---------- saving ----------
// Locally, changes save automatically after a short pause and saves never
// overlap. Online, changes collect until you press publish.

let dirty = false;
let saveTimer;
let saving = Promise.resolve();

function changed(delay = 600) {
  dirty = true;
  if (!store.autosave) {
    setStatus("unpublished changes");
    publishBtn.disabled = false;
    return;
  }
  setStatus("editing…");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, delay);
}

function save() {
  if (!store.autosave) return Promise.resolve();
  clearTimeout(saveTimer);
  saving = saving.then(async () => {
    if (!dirty) return;
    dirty = false;
    setStatus("saving…");
    try {
      const saved = await store.save(content);
      content.site.lastUpdate = saved.site.lastUpdate;
      const t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      setStatus(`saved ${t}`);
    } catch (e) {
      dirty = true;
      setStatus(`not saved: ${e.message}`, true);
    }
  });
  return saving;
}

async function publish() {
  publishBtn.disabled = true;
  setStatus("publishing…");
  try {
    content.site.lastUpdate = new Date().toISOString().slice(0, 10);
    await store.publish(content);
    dirty = false;
    setStatus("published. the live site updates in about a minute.");
  } catch (e) {
    publishBtn.disabled = false;
    setStatus(`not published: ${e.message}`, true);
  }
}

window.addEventListener("beforeunload", (e) => {
  if (dirty) e.preventDefault();
});

// ---------- sidebar ----------

function renderSidebar() {
  $("nav-settings").classList.toggle("active", view.type === "settings");
  $("project-list").replaceChildren(
    ...content.projects.map((p) =>
      h(
        "li",
        {},
        h(
          "button",
          {
            class: `nav-item${view.project === p ? " active" : ""}`,
            onclick: () => show({ type: "project", project: p }),
          },
          h("span", {}, p.title || "untitled"),
          h("span", { class: "n" }, String(p.photos.length))
        )
      )
    )
  );
}

function show(next) {
  view = next;
  renderSidebar();
  renderPanel();
  window.scrollTo(0, 0);
}

function renderPanel() {
  panel.replaceChildren(view.type === "project" ? projectPanel(view.project) : settingsPanel());
}

// ---------- settings ----------

function field(label, input, { wide = false, hint } = {}) {
  return h("label", { class: `field${wide ? " wide" : ""}` }, h("span", {}, label), input, hint && h("small", {}, hint));
}

function textInput(obj, key, { event = "input", multiline = false, onChange, ...attrs } = {}) {
  const el = h(multiline ? "textarea" : "input", { value: obj[key] || "", ...attrs });
  el.addEventListener(event, () => {
    obj[key] = el.value;
    if (onChange) onChange(el);
    changed();
  });
  return el;
}

// A typo in the time zone would stop the site from building, so fall back to UTC.
function checkTimezone(el) {
  try {
    if (el.value) new Intl.DateTimeFormat("en", { timeZone: el.value });
  } catch {
    el.value = content.site.timezone = "UTC";
    setStatus("unknown time zone, kept UTC. pick one from the list", true);
  }
}

function settingsPanel() {
  const s = content.site;
  const zones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
  return h(
    "div",
    {},
    h("h1", { class: "display" }, "settings"),
    h(
      "div",
      { class: "fields" },
      field("name", textInput(s, "name")),
      field("location", textInput(s, "location"), { hint: "shown in the footer and on contact" }),
      field("time zone", textInput(s, "timezone", { event: "change", list: "zones", onChange: checkTimezone }), {
        hint: "for the footer clock, e.g. Europe/Paris",
      }),
      h("datalist", { id: "zones" }, zones.map((z) => h("option", { value: z }))),
      field("email", textInput(s, "email", { type: "email" })),
      field("instagram", textInput(s, "instagram"), { hint: "handle without @" }),
      field("about", textInput(s, "about", { multiline: true, rows: 10 }), {
        wide: true,
        hint: "leave a blank line between paragraphs",
      })
    ),
    content.site.lastUpdate && h("p", { class: "empty" }, `site last updated ${content.site.lastUpdate}`)
  );
}

// ---------- project ----------

function projectPanel(p) {
  const i = content.projects.indexOf(p);
  const heading = h("h1", { class: "display" }, p.title || "untitled");

  const slugInput = textInput(p, "slug", {
    event: "change",
    onChange: (el) => {
      autoSlug.delete(p);
      p.slug = uniqueSlug(slugify(el.value), p);
      el.value = p.slug;
    },
  });

  const titleInput = textInput(p, "title", {
    onChange: (el) => {
      heading.textContent = el.value || "untitled";
      if (autoSlug.has(p)) slugInput.value = p.slug = uniqueSlug(slugify(el.value), p);
      renderSidebar();
    },
  });

  const tiles = h("div", { class: "tiles" });
  const fileInput = h("input", {
    type: "file",
    accept: "image/*",
    multiple: true,
    onchange: () => {
      addFiles(p, fileInput.files);
      fileInput.value = "";
    },
  });
  const dropzone = h("label", { class: "dropzone" }, fileInput, "drop photos here, or click to choose");
  for (const el of [dropzone, tiles]) acceptFileDrops(el, p);

  const panelEl = h(
    "div",
    {},
    heading,
    h(
      "div",
      { class: "fields" },
      field("title", titleInput),
      field("year", textInput(p, "year"), { hint: "e.g. 2024, 2021–, ongoing" }),
      field("address", slugInput, { hint: `the link is project.html?p=${p.slug}` }),
      h(
        "div",
        { class: "field" },
        h("span", {}, "position on home page"),
        h(
          "div",
          { class: "order" },
          `${pad(i)} of ${String(content.projects.length).padStart(2, "0")}`,
          h("button", { disabled: i === 0, onclick: () => reorderProject(p, -1) }, "↑ up"),
          h("button", { disabled: i === content.projects.length - 1, onclick: () => reorderProject(p, 1) }, "↓ down")
        )
      ),
      field("description", textInput(p, "description", { multiline: true }), {
        wide: true,
        hint: "leave a blank line between paragraphs",
      })
    ),
    h("h2", {}, h("span", {}, "photos"), h("span", { class: "hint" }, "drag to reorder · ★ sets the home-page preview")),
    dropzone,
    tiles,
    h("button", { class: "danger", onclick: () => deleteProject(p) }, "delete project")
  );

  panelEl.tiles = tiles;
  renderTiles(p, tiles);
  return panelEl;
}

function reorderProject(p, dir) {
  const i = content.projects.indexOf(p);
  const j = i + dir;
  if (j < 0 || j >= content.projects.length) return;
  content.projects.splice(i, 1);
  content.projects.splice(j, 0, p);
  changed(0);
  renderSidebar();
  renderPanel();
}

function currentTiles(p) {
  return view.project === p ? panel.firstChild && panel.firstChild.tiles : null;
}

function renderTiles(p, tiles = currentTiles(p)) {
  if (!tiles) return;
  const cover = p.cover || p.photos[0];
  let dragFrom = null;

  const items = p.photos.map((photo, i) => {
    const tile = h(
      "div",
      {
        class: "tile",
        draggable: "true",
        ondragstart: (e) => {
          dragFrom = i;
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setData("text/plain", String(i));
          tile.classList.add("dragging");
        },
        ondragend: () => {
          dragFrom = null;
          for (const t of tiles.children) t.classList.remove("dragging", "drop-before");
        },
        ondragover: (e) => {
          if (dragFrom === null) return;
          e.preventDefault();
          tile.classList.add("drop-before");
        },
        ondragleave: () => tile.classList.remove("drop-before"),
        ondrop: (e) => {
          if (dragFrom === null) return;
          e.preventDefault();
          e.stopPropagation();
          move(p.photos, dragFrom, i);
          dragFrom = null;
          changed(0);
          renderTiles(p);
        },
      },
      h("div", { class: "thumb" }, h("img", { src: store.src(photo), alt: "", loading: "lazy" })),
      h(
        "div",
        { class: "row" },
        h("span", { class: "n" }, pad(i), photo === cover && h("span", { class: "cover-tag" }, "cover")),
        h(
          "span",
          { class: "actions" },
          h("button", { title: "use as home-page preview", onclick: () => setCover(p, photo) }, "★"),
          h("button", { title: "remove photo", onclick: () => deletePhoto(p, photo) }, "×")
        )
      )
    );
    return tile;
  });

  const pending = (pendingUploads.get(p) || []).map((u) =>
    h("div", { class: "tile pending" }, h("div", { class: "thumb" }, u.state), h("div", { class: "row" }, h("span", { class: "n" }, u.name)))
  );

  tiles.replaceChildren(...items, ...pending);
  if (!items.length && !pending.length) tiles.append(h("p", { class: "empty" }, "no photos yet"));

  // Dropping a dragged photo on empty space moves it to the end.
  tiles.ondragover = (e) => {
    if (dragFrom !== null) e.preventDefault();
  };
  tiles.ondrop = (e) => {
    if (dragFrom === null) return;
    e.preventDefault();
    move(p.photos, dragFrom, p.photos.length);
    dragFrom = null;
    changed(0);
    renderTiles(p);
  };
}

function setCover(p, photo) {
  if (p.cover === photo) delete p.cover;
  else p.cover = photo;
  changed(0);
  renderTiles(p);
}

async function deletePhoto(p, photo) {
  p.photos = p.photos.filter((x) => x !== photo);
  if (p.cover === photo) delete p.cover;
  changed(0);
  renderTiles(p);
  renderSidebar();
  await save();
  try {
    await store.remove(photo);
  } catch (e) {
    setStatus(`photo removed, but couldn't move file to trash: ${e.message}`, true);
  }
}

async function deleteProject(p) {
  const n = p.photos.length;
  const where = store.mode === "local" ? "photo files are moved to photos/.trash" : "photo files stay in the repository history";
  if (!confirm(`delete "${p.title || "untitled"}"${n ? ` and its ${n} photos` : ""}?\n\n${where}`)) return;
  content.projects = content.projects.filter((x) => x !== p);
  show({ type: "settings" });
  changed(0);
  await save();
  for (const photo of p.photos) {
    try {
      await store.remove(photo);
    } catch (e) {
      setStatus(`project deleted, but some files couldn't be moved to trash: ${e.message}`, true);
    }
  }
}

function newProject() {
  const p = { slug: uniqueSlug("untitled"), title: "untitled", year: "", description: "", photos: [] };
  autoSlug.add(p);
  content.projects.push(p);
  changed(0);
  show({ type: "project", project: p });
  const title = panel.querySelector("input");
  title.focus();
  title.select();
}

// ---------- uploads ----------

function acceptFileDrops(el, p) {
  el.addEventListener("dragover", (e) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    el.classList.add("over");
  });
  el.addEventListener("dragleave", () => el.classList.remove("over"));
  el.addEventListener("drop", (e) => {
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    el.classList.remove("over");
    addFiles(p, e.dataTransfer.files);
  });
}

// Shrinks the image to MAX_SIZE and re-encodes as JPEG. This also drops
// camera metadata such as GPS location.
async function resize(file) {
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error("can't read this file (if it's heic, export it as jpeg first)");
  }
  const scale = Math.min(1, MAX_SIZE / Math.max(bitmap.width, bitmap.height));
  const canvas = h("canvas", { width: Math.round(bitmap.width * scale), height: Math.round(bitmap.height * scale) });
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("couldn't process image"))), "image/jpeg", QUALITY)
  );
}

async function addFiles(p, fileList) {
  const files = [...fileList];
  if (!files.length) return;
  const queue = pendingUploads.get(p) || [];
  pendingUploads.set(p, queue);
  const jobs = files.map((f) => ({ file: f, name: f.name, state: "waiting…" }));
  queue.push(...jobs);
  renderTiles(p);

  let failed = 0;
  for (const job of jobs) {
    try {
      job.state = "resizing…";
      renderTiles(p);
      const blob = await resize(job.file);
      job.state = "uploading…";
      renderTiles(p);
      const path = await store.upload(p.slug, blob);
      p.photos.push(path);
      queue.splice(queue.indexOf(job), 1);
      changed(0);
    } catch (e) {
      failed++;
      job.state = e.message;
      setTimeout(() => {
        queue.splice(queue.indexOf(job), 1);
        renderTiles(p);
      }, 8000);
    }
    renderTiles(p);
    renderSidebar();
  }
  if (failed) setStatus(`${failed} of ${jobs.length} photos couldn't be added`, true);
}

// ---------- start ----------

function signInPanel(error) {
  const input = h("input", { type: "password", autocomplete: "off", placeholder: "github_pat_…" });
  const remember = h("input", { type: "checkbox" });
  const form = h(
    "form",
    {
      class: "fields",
      onsubmit: (e) => {
        e.preventDefault();
        if (!input.value.trim()) return;
        store.signIn(input.value, remember.checked);
        start();
      },
    },
    field("access token", input, { wide: true }),
    h("label", { class: "check" }, remember, " remember on this device"),
    h("div", { class: "wide" }, h("button", { class: "primary", type: "submit" }, "connect"))
  );
  const tokenUrl = "https://github.com/settings/personal-access-tokens/new";
  return h(
    "div",
    { class: "signin" },
    h("h1", { class: "display" }, "connect"),
    h("p", {}, `this dashboard saves straight to the github repository ${store.repo}. to unlock it, paste a github access token.`),
    h(
      "ol",
      {},
      h("li", {}, "open ", h("a", { href: tokenUrl, target: "_blank", rel: "noopener" }, "github → new fine-grained token ↗")),
      h("li", {}, "repository access: only select repositories → ", h("b", {}, store.repo.split("/")[1])),
      h("li", {}, "repository permissions → contents: read and write"),
      h("li", {}, "generate the token, copy it and paste it below")
    ),
    error && h("p", { class: "error" }, error),
    form
  );
}

function setSignedInUi(signedIn) {
  $("sidebar").hidden = !signedIn;
  publishBtn.hidden = store.autosave || !signedIn;
  $("sign-out").hidden = store.autosave || !signedIn;
}

async function start() {
  if (store.needsSignIn()) {
    setSignedInUi(false);
    panel.replaceChildren(signInPanel());
    panel.querySelector("input").focus();
    return;
  }
  setSignedInUi(true);
  setStatus("loading…");
  try {
    content = await store.load();
  } catch (e) {
    if ([401, 403, 404].includes(e.status)) {
      store.signOut();
      setSignedInUi(false);
      setStatus("");
      panel.replaceChildren(signInPanel(e.message));
      return;
    }
    setStatus("couldn't load", true);
    panel.replaceChildren(h("p", { class: "empty" }, e.message));
    return;
  }
  setStatus(store.autosave ? "" : `connected to ${store.repo}`);
  if (content.projects.length) view = { type: "project", project: content.projects[0] };
  show(view);
}

$("nav-settings").addEventListener("click", () => show({ type: "settings" }));
$("add-project").addEventListener("click", newProject);
publishBtn.addEventListener("click", publish);
$("sign-out").addEventListener("click", () => {
  if (dirty && !confirm("you have unpublished changes. sign out anyway?")) return;
  dirty = false;
  store.signOut();
  location.reload();
});

start();
