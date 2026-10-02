// Builds the public site into dist/, ready to upload to a static host:
// checks content.json, generates js/data.js from it, and copies the pages,
// styles, scripts, photos and the dashboard. Leaves out the local server
// and photos/.trash.
// Run with `node build.js` (or `npm run build`).

const fs = require("node:fs");
const path = require("node:path");
const { validate, renderDataJs } = require("./lib/content");

const ROOT = __dirname;
const DIST = path.join(ROOT, "dist");
const PUBLIC = ["index.html", "project.html", "about.html", "contact.html", "css", "js", "photos", "admin"];

let content;
try {
  content = validate(JSON.parse(fs.readFileSync(path.join(ROOT, "content.json"), "utf8")));
} catch (e) {
  console.error(`content.json is not valid: ${e.message}`);
  process.exit(1);
}

// Every local photo listed must exist, or the site would show broken images.
const missing = content.projects
  .flatMap((p) => p.photos)
  .filter((p) => !p.startsWith("https://") && !fs.existsSync(path.join(ROOT, p)));
if (missing.length) {
  console.error(`content.json lists photos that don't exist:\n  ${missing.join("\n  ")}`);
  process.exit(1);
}

fs.rmSync(DIST, { recursive: true, force: true });
fs.mkdirSync(DIST);

let files = 0;
let bytes = 0;
for (const entry of PUBLIC) {
  const src = path.join(ROOT, entry);
  if (!fs.existsSync(src)) continue;
  fs.cpSync(src, path.join(DIST, entry), {
    recursive: true,
    // Skip hidden files and folders such as photos/.trash
    filter: (p) => {
      if (path.basename(p).startsWith(".")) return false;
      if (fs.statSync(p).isFile()) {
        files++;
        bytes += fs.statSync(p).size;
      }
      return true;
    },
  });
}

fs.mkdirSync(path.join(DIST, "js"), { recursive: true });
fs.writeFileSync(path.join(DIST, "js", "data.js"), renderDataJs(content));

console.log(`built dist/ — ${files} files, ${(bytes / 1024 / 1024).toFixed(1)} MB`);
