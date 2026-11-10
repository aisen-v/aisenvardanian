# photo website

A minimal photography portfolio: plain HTML/CSS/JS with no build tools, plus a dashboard for managing it.

- live site: https://aisen-v.github.io/aisenvardanian/
- online dashboard: https://aisen-v.github.io/aisenvardanian/admin/

## Dashboard

- **settings**: name, location, time zone, email, instagram, about text
- **projects**: create, rename, reorder, delete
- **photos**: drag files in (or click to choose), drag to reorder, ★ to pick the home-page preview, × to remove

Uploads are resized in the browser to 2000px JPEGs, which also strips camera metadata like GPS location.

### Online (any device)

Open `/admin/` on the live site. The first time, it asks for a GitHub access token:

1. github.com → settings → developer settings → [fine-grained tokens → generate new token](https://github.com/settings/personal-access-tokens/new)
2. repository access: **only select repositories** → `aisenvardanian`
3. repository permissions → **contents: read and write**
4. paste the token into the dashboard. Tick "remember on this device" only on your own devices.

Edits collect as a draft. **publish** saves everything as one commit, and GitHub rebuilds the site in about a minute. Removed photos stay in the git history.

The token only works on this one repository. If a device is lost, delete the token on GitHub. Without a token the admin page is only a sign-in screen.

### Local

```
node server.js
```

Then open http://localhost:8080/admin/. Changes save automatically to your files (removed photos go to `photos/.trash/`). On start, the server pulls anything you published online. When you're done, put the changes live with:

```
npm run publish-site
```

## How content is stored

- `content.json` holds all content.
- `js/data.js` is generated from it (by the local server, and by `build.js` when GitHub publishes). It isn't stored in git.
- `photos/<project>/` holds the images.

## Publishing

Every push to `main` runs `.github/workflows/deploy.yml`: `node build.js` checks content.json, generates `dist/`, and deploys it to GitHub Pages. If content.json is broken or lists a missing photo, the build stops and the live site keeps its previous version.

## Files

- `index.html`, `project.html`, `about.html`, `contact.html`: public pages
- `css/style.css`: site styling
- `js/common.js`, `js/project.js`: page scripts
- `admin/`: dashboard (`storage.js` handles saving locally or to GitHub)
- `lib/content.js`: content checks, shared by the server and the build
- `server.js`: local server
- `build.js`: builds `dist/`
- `publish.js`: commits and pushes local changes
