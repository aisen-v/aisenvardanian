// Content checks and the js/data.js generator, shared by server.js and build.js.

const SLUG = /^[a-z0-9][a-z0-9-]{0,63}$/;
const SITE_FIELDS = ["name", "location", "timezone", "email", "instagram", "about", "lastUpdate"];

class ContentError extends Error {}

function isValidPhoto(p) {
  if (typeof p !== "string" || p.length > 500) return false;
  if (/^https:\/\/[^\s"'<>]+$/.test(p)) return true;
  return /^photos\/[a-z0-9-]+\/[A-Za-z0-9._-]+$/.test(p) && !p.includes("..");
}

function str(v, max = 5000) {
  if (v == null) return "";
  if (typeof v !== "string") throw new ContentError("expected text");
  return v.slice(0, max);
}

// Returns a clean copy with only known fields, or throws ContentError.
function validate(c) {
  if (!c || typeof c !== "object" || !c.site || !Array.isArray(c.projects)) {
    throw new ContentError("invalid content");
  }
  const site = {};
  for (const f of SITE_FIELDS) site[f] = str(c.site[f], f === "about" ? 20000 : 200);
  if (site.timezone) {
    try {
      new Intl.DateTimeFormat("en", { timeZone: site.timezone });
    } catch {
      throw new ContentError(`unknown time zone "${site.timezone}"`);
    }
  }

  const seen = new Set();
  const projects = c.projects.map((p) => {
    if (!p || !SLUG.test(p.slug)) throw new ContentError(`invalid project address "${p && p.slug}"`);
    if (seen.has(p.slug)) throw new ContentError(`two projects use the address "${p.slug}"`);
    seen.add(p.slug);
    if (!Array.isArray(p.photos) || !p.photos.every(isValidPhoto)) {
      throw new ContentError(`invalid photo list in "${p.slug}"`);
    }
    const out = {
      slug: p.slug,
      title: str(p.title, 200) || p.slug,
      year: str(p.year, 100),
      description: str(p.description, 20000),
      photos: p.photos,
    };
    if (p.cover && p.photos.includes(p.cover)) out.cover = p.cover;
    return out;
  });
  return { site, projects };
}

function renderDataJs(content) {
  return (
    "// Generated from content.json. Edit content through the dashboard (/admin).\n\n" +
    `const SITE = ${JSON.stringify(content.site, null, 2)};\n\n` +
    `const PROJECTS = ${JSON.stringify(content.projects, null, 2)};\n`
  );
}

module.exports = { SLUG, ContentError, isValidPhoto, validate, renderDataJs };
