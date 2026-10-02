// Shared header and footer, filled in on every page.

document.title = document.title ? `${document.title} — ${SITE.name}` : SITE.name;

for (const el of document.querySelectorAll("[data-site-name]")) el.textContent = SITE.name;

const here = location.pathname.split("/").pop() || "index.html";
for (const a of document.querySelectorAll(".top nav a")) {
  if (a.getAttribute("href") === here) a.setAttribute("aria-current", "page");
}

const footer = document.querySelector(".footer");
if (footer) {
  const updated = document.createElement("span");
  updated.textContent = `last update ${SITE.lastUpdate}`;
  const clock = document.createElement("span");
  footer.append(updated, clock);

  const tick = () => {
    const time = new Date().toLocaleTimeString("en-GB", {
      timeZone: SITE.timezone,
      hour: "2-digit",
      minute: "2-digit",
    });
    clock.textContent = `${SITE.location} ${time}`;
  };
  tick();
  setInterval(tick, 30_000);
}
