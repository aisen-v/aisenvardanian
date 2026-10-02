// Copies only the public site into dist/, ready to upload to a static host.
// Leaves out the dashboard, server, content.json and photos/.trash.
// Run with `node build.js` (or `npm run build`).

const fs = require("node:fs");
const path = require("node:path");

const ROOT = __dirname;
const DIST = path.join(ROOT, "dist");
const PUBLIC = ["index.html", "project.html", "about.html", "contact.html", "css", "js", "photos"];

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

console.log(`built dist/ — ${files} files, ${(bytes / 1024 / 1024).toFixed(1)} MB`);
