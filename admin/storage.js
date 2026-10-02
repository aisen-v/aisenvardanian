// Where the dashboard reads and writes content.
//
// - local:  on localhost, through server.js. Every change saves right away.
// - github: anywhere else (e.g. GitHub Pages), through the GitHub API with a
//           personal access token. Changes collect as a draft until "publish",
//           which makes one commit; GitHub then rebuilds the site.
//
// On localhost, add ?github=owner/repo to the address to use github mode.

function createStore() {
  const forced = new URLSearchParams(location.search).get("github");
  const isLocal = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  if (isLocal && !forced) return localStore();

  let owner, repo;
  if (forced) [owner, repo] = forced.split("/");
  else {
    // https://<owner>.github.io/<repo>/admin/  or  https://<owner>.github.io/admin/
    owner = location.hostname.split(".")[0];
    const first = location.pathname.split("/")[1];
    repo = first && first !== "admin" ? first : `${owner}.github.io`;
  }
  return githubStore(owner, repo);
}

// Photos are stored as "photos/<project>/<file>"; the dashboard lives one folder down.
const sitePath = (p) => (/^https?:/.test(p) ? p : `../${p}`);

function randomName() {
  const rand = Math.random().toString(16).slice(2, 8);
  return `${Date.now().toString(36)}-${rand}.jpg`;
}

// ---------- local ----------

function localStore() {
  async function api(method, url, body, type = "application/json") {
    const headers = { "X-Dashboard": "1" };
    if (body !== undefined) headers["Content-Type"] = type;
    const res = await fetch(url, {
      method,
      headers,
      body: body !== undefined && type === "application/json" ? JSON.stringify(body) : body,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
    return data;
  }

  return {
    mode: "local",
    autosave: true,
    needsSignIn: () => false,
    load: () =>
      api("GET", "/api/content").catch(() => {
        throw new Error("the dashboard needs the local server. in the project folder, run: node server.js");
      }),
    save: (content) => api("PUT", "/api/content", content),
    src: sitePath,
    upload: async (slug, blob) => (await api("POST", `/api/photos/${encodeURIComponent(slug)}`, blob, "image/jpeg")).path,
    remove: (path) => api("POST", "/api/trash", { path }),
  };
}

// ---------- github ----------

function githubStore(owner, repo) {
  const API = `https://api.github.com/repos/${owner}/${repo}`;
  const BRANCH = "main";
  const KEY = `dashboard-token:${owner}/${repo}`;

  const storage = (kind) => {
    try {
      return window[kind];
    } catch {
      return null;
    }
  };
  let token = storage("sessionStorage")?.getItem(KEY) || storage("localStorage")?.getItem(KEY) || "";

  const uploads = new Map(); // path -> { sha, url } for photos not yet published
  const previews = new Map(); // path -> object URL, kept until the live site has the file
  const removed = new Set(); // published photos to delete on the next publish

  async function gh(method, path, body) {
    const res = await fetch(API + path, {
      method,
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) return data;
    const err = new Error(
      res.status === 401
        ? "github didn't accept the token. it may be mistyped or expired."
        : res.status === 403 || res.status === 404
          ? `the token can't access ${owner}/${repo}. check it has "contents: read and write" for this repository.`
          : data.message || `github error ${res.status}`
    );
    err.status = res.status;
    throw err;
  }

  const bytesToBase64 = (bytes) => {
    let s = "";
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(s);
  };
  const base64ToText = (b64) =>
    new TextDecoder().decode(Uint8Array.from(atob(b64.replace(/\s/g, "")), (c) => c.charCodeAt(0)));

  return {
    mode: "github",
    autosave: false,
    repo: `${owner}/${repo}`,
    needsSignIn: () => !token,

    signIn(value, remember) {
      token = value.trim();
      storage(remember ? "localStorage" : "sessionStorage")?.setItem(KEY, token);
    },

    signOut() {
      token = "";
      storage("localStorage")?.removeItem(KEY);
      storage("sessionStorage")?.removeItem(KEY);
    },

    async load() {
      const ref = await gh("GET", `/git/ref/heads/${BRANCH}`);
      const file = await gh("GET", `/contents/content.json?ref=${ref.object.sha}`);
      return JSON.parse(base64ToText(file.content));
    },

    src: (p) => previews.get(p) || sitePath(p),

    // Uploads the image as a git blob now; it joins the site on the next publish.
    async upload(slug, blob) {
      const path = `photos/${slug}/${randomName()}`;
      const content = bytesToBase64(new Uint8Array(await blob.arrayBuffer()));
      const { sha } = await gh("POST", "/git/blobs", { content, encoding: "base64" });
      const url = URL.createObjectURL(blob);
      uploads.set(path, { sha });
      previews.set(path, url);
      return path;
    },

    async remove(path) {
      if (/^https?:/.test(path)) return;
      if (uploads.has(path)) uploads.delete(path);
      else removed.add(path);
    },

    // One commit with content.json, new photos and removed photos.
    async publish(content) {
      const ref = await gh("GET", `/git/ref/heads/${BRANCH}`);
      const head = await gh("GET", `/git/commits/${ref.object.sha}`);
      const used = new Set(content.projects.flatMap((p) => p.photos));

      const tree = [
        { path: "content.json", mode: "100644", type: "blob", content: JSON.stringify(content, null, 2) + "\n" },
      ];
      for (const [path, { sha }] of uploads) {
        if (used.has(path)) tree.push({ path, mode: "100644", type: "blob", sha });
      }
      for (const path of removed) {
        if (!used.has(path)) tree.push({ path, mode: "100644", type: "blob", sha: null });
      }

      const newTree = await gh("POST", "/git/trees", { base_tree: head.tree.sha, tree });
      const commit = await gh("POST", "/git/commits", {
        message: "update site from dashboard",
        tree: newTree.sha,
        parents: [ref.object.sha],
      });
      await gh("PATCH", `/git/refs/heads/${BRANCH}`, { sha: commit.sha });

      uploads.clear();
      removed.clear();
      return commit;
    },
  };
}
