// Local server: serves the site and the /admin dashboard, and saves changes.
// Run with `node server.js`, then open http://localhost:8080/admin
//
// content.json is the source of truth. Every save regenerates js/data.js,
// which is what the public pages read, so the site itself stays static.

const http = require("node:http");
const fs = require("node:fs/promises");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const { SLUG, ContentError, isValidPhoto, validate, renderDataJs } = require("./lib/content");

const ROOT = __dirname;
const PORT = Number(process.env.PORT) || 8080;
const CONTENT = path.join(ROOT, "content.json");
const DATA_JS = path.join(ROOT, "js", "data.js");
const PHOTOS = path.join(ROOT, "photos");
const TRASH = path.join(PHOTOS, ".trash");
const MAX_UPLOAD = 30 * 1024 * 1024;
const MAX_JSON = 2 * 1024 * 1024;

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".md": "text/plain; charset=utf-8",
};
const UPLOAD_EXT = { "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp" };

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// ---------- content ----------

async function writeAtomic(file, text) {
  const tmp = `${file}.${process.pid}.tmp`;
  await fs.writeFile(tmp, text, "utf8");
  await fs.rename(tmp, file);
}

async function loadContent() {
  return JSON.parse(await fs.readFile(CONTENT, "utf8"));
}

async function saveContent(input) {
  const content = validate(input);
  content.site.lastUpdate = new Date().toISOString().slice(0, 10);
  await writeAtomic(CONTENT, JSON.stringify(content, null, 2) + "\n");
  await writeAtomic(DATA_JS, renderDataJs(content));
  return content;
}

// ---------- photos ----------

async function uploadPhoto(req, slug) {
  if (!SLUG.test(slug)) throw new HttpError(400, "invalid project address");
  const type = (req.headers["content-type"] || "").split(";")[0].trim();
  const ext = UPLOAD_EXT[type];
  if (!ext) throw new HttpError(415, "only jpeg, png or webp images");
  const body = await readBody(req, MAX_UPLOAD);
  if (!body.length) throw new HttpError(400, "empty file");

  const dir = path.join(PHOTOS, slug);
  await fs.mkdir(dir, { recursive: true });
  const name = `${Date.now().toString(36)}-${crypto.randomBytes(3).toString("hex")}${ext}`;
  await fs.writeFile(path.join(dir, name), body);
  return { path: `photos/${slug}/${name}` };
}

// Moves a local photo into photos/.trash instead of deleting it.
async function trashPhoto(photo) {
  if (!isValidPhoto(photo)) throw new HttpError(400, "invalid photo");
  if (photo.startsWith("https://")) return { trashed: false };
  const file = path.join(ROOT, photo);
  if (!file.startsWith(PHOTOS + path.sep)) throw new HttpError(400, "invalid photo");
  await fs.mkdir(TRASH, { recursive: true });
  const dest = path.join(TRASH, `${Date.now().toString(36)}-${photo.split("/").slice(1).join("-")}`);
  try {
    await fs.rename(file, dest);
  } catch (e) {
    if (e.code === "ENOENT") return { trashed: false };
    throw e;
  }
  return { trashed: true };
}

// ---------- http ----------

function readBody(req, limit) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (c) => {
      size += c.length;
      if (size > limit) {
        reject(new HttpError(413, "file too large"));
        req.destroy();
      } else chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

async function readJson(req) {
  try {
    return JSON.parse((await readBody(req, MAX_JSON)).toString("utf8"));
  } catch (e) {
    throw e instanceof HttpError ? e : new HttpError(400, "invalid json");
  }
}

function send(res, status, data) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  res.end(JSON.stringify(data));
}

// Only accept API calls made by the dashboard on this machine: the Host check
// blocks DNS-rebinding, and the custom header can't be sent cross-site without CORS.
function checkApiRequest(req) {
  const host = (req.headers.host || "").replace(/:\d+$/, "");
  if (!["localhost", "127.0.0.1", "[::1]"].includes(host)) throw new HttpError(403, "forbidden");
  if (req.method !== "GET" && req.headers["x-dashboard"] !== "1") throw new HttpError(403, "forbidden");
}

async function handleApi(req, res, url) {
  checkApiRequest(req);
  const route = `${req.method} ${url.pathname}`;

  if (route === "GET /api/content") return send(res, 200, await loadContent());
  if (route === "PUT /api/content") return send(res, 200, await saveContent(await readJson(req)));
  if (route === "POST /api/trash") return send(res, 200, await trashPhoto((await readJson(req)).path));

  const upload = url.pathname.match(/^\/api\/photos\/([^/]+)$/);
  if (upload && req.method === "POST") return send(res, 200, await uploadPhoto(req, decodeURIComponent(upload[1])));

  throw new HttpError(404, "not found");
}

async function serveStatic(req, res, url) {
  let pathname = decodeURIComponent(url.pathname);
  if (pathname === "/admin") {
    res.writeHead(301, { Location: "/admin/" });
    return res.end();
  }
  if (pathname.endsWith("/")) pathname += "index.html";

  const file = path.join(ROOT, pathname);
  if (!file.startsWith(ROOT + path.sep) || file.includes(`${path.sep}.`)) throw new HttpError(404, "not found");

  let data;
  try {
    data = await fs.readFile(file);
  } catch {
    throw new HttpError(404, "not found");
  }
  res.writeHead(200, {
    "Content-Type": TYPES[path.extname(file).toLowerCase()] || "application/octet-stream",
    "Cache-Control": "no-store",
  });
  res.end(data);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  try {
    if (url.pathname.startsWith("/api/")) await handleApi(req, res, url);
    else await serveStatic(req, res, url);
  } catch (e) {
    const status = e instanceof HttpError ? e.status : e instanceof ContentError ? 400 : 500;
    if (status === 500) console.error(e);
    if (!res.headersSent) {
      if (url.pathname.startsWith("/api/")) send(res, status, { error: status === 500 ? "server error" : e.message });
      else {
        res.writeHead(status, { "Content-Type": "text/plain" });
        res.end(status === 404 ? "not found" : "error");
      }
    }
  }
});

// Bring in changes published from the online dashboard, if this is a git
// checkout with a remote. Fast-forward only, so local work is never touched.
try {
  execFileSync("git", ["pull", "--ff-only", "--quiet"], { cwd: ROOT, stdio: "pipe", timeout: 20000 });
  console.log("pulled latest changes from github");
} catch {
  console.log("couldn't pull from github (offline, or local changes not yet published) — using local files");
}

// js/data.js isn't stored in git, so make sure it matches content.json.
require("node:fs").writeFileSync(DATA_JS, renderDataJs(validate(require(CONTENT))));

server.listen(PORT, "127.0.0.1", () => {
  console.log(`site       http://localhost:${PORT}/`);
  console.log(`dashboard  http://localhost:${PORT}/admin/`);
});
