// Saves all local changes to git and pushes them; GitHub then rebuilds the live site.
// Run with `node publish.js` (or `npm run publish-site`).

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

// Include anything published from the online dashboard first.
try {
  git("pull", "--rebase", "--quiet");
} catch {
  try {
    git("rebase", "--abort");
  } catch {}
  console.error(
    "couldn't combine your local changes with changes made in the online dashboard.\n" +
      "the same thing was probably edited in both places. nothing was published."
  );
  process.exit(1);
}

console.log("pushing to github…");
execFileSync("git", ["push"], { cwd: __dirname, stdio: "inherit" });
console.log("done. the live site updates in about a minute.");
