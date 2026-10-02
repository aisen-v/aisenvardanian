# photo website

A minimal photography portfolio: plain HTML/CSS/JS, no build step, plus a local dashboard for managing it.

## Run it

```
node server.js
```

- site: http://localhost:8080/
- dashboard: http://localhost:8080/admin/

The server only listens on your own computer. Nothing needs to be installed (Node 18+).

## Dashboard

- **settings**: name, location, time zone, email, instagram, about text
- **projects**: create, rename, reorder, delete
- **photos**: drag files in (or click to choose), drag to reorder, ★ to pick the home-page preview, × to remove

Changes save automatically. Uploads are resized in the browser to 2000px JPEGs, which also strips camera metadata like GPS location. Removed photos are moved to `photos/.trash/` rather than deleted, so you can recover them. Empty that folder whenever you like.

## How content is stored

- `content.json` holds all content. The dashboard edits it.
- `js/data.js` is generated from it on every save. The public pages read this file. Don't edit it by hand.
- `photos/<project>/` holds the uploaded images.

## Publishing

The public site is static. Upload everything **except** `server.js`, `admin/`, `content.json`, `package.json` and `photos/.trash/` to any static host (Netlify, GitHub Pages, Cloudflare Pages…). To update the live site, make changes in the dashboard, then upload again.

## Files

- `index.html`: home page with the project index
- `project.html`: one template for every project (`project.html?p=<slug>`)
- `about.html`, `contact.html`
- `css/style.css`: site styling
- `js/common.js`: shared header and footer (name, footer clock)
- `js/project.js`: project page and photo viewer
- `admin/`: dashboard
- `server.js`: local server and save API
