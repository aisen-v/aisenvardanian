// Saves all changes to git and pushes them; GitHub then rebuilds the live site.
// Run with `node publish.js` (or `npm run publish`).

const { execFileSync } = require("node:child_process");

const git = (...args) => execFileSync("git", args, { cwd: __dirname, stdio: "pipe" }).toString().trim();

git("add", "-A");
if (!git("status", "--porcelain")) {
  console.log("nothing new to publish");
} else {
  const stamp = new Date().toISOString().slice(0, 16).replace("T", " ");
  git("commit", "-m", `update site ${stamp}`);
  console.log("committed changes");
}

console.log("pushing to github…");
execFileSync("git", ["push"], { cwd: __dirname, stdio: "inherit" });
console.log("done. the live site updates in about a minute.");
