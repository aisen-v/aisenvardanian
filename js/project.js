const slug = new URLSearchParams(location.search).get("p");
const index = PROJECTS.findIndex((p) => p.slug === slug);
const project = PROJECTS[index];

if (!project) {
  location.replace("index.html");
} else {
  const n = project.photos.length;
  const pad = (i) => String(i + 1).padStart(2, "0");

  document.title = project.title;
  document.getElementById("title").textContent = project.title;
  document.getElementById("meta").textContent = [project.year, `${n} photographs`]
    .filter(Boolean)
    .join(" · ");
  document.getElementById("description").textContent = project.description || "";

  const sequence = document.getElementById("sequence");
  project.photos.forEach((src, i) => {
    const fig = document.createElement("figure");
    const img = document.createElement("img");
    img.src = src;
    img.alt = `${project.title} ${i + 1}`;
    img.loading = "lazy";
    const cap = document.createElement("figcaption");
    cap.textContent = pad(i);
    fig.append(img, cap);
    fig.addEventListener("click", () => openBox(i));
    sequence.append(fig);
  });

  const next = PROJECTS[(index + 1) % PROJECTS.length];
  document.getElementById("next-link").href = `project.html?p=${encodeURIComponent(next.slug)}`;
  document.getElementById("next-title").textContent = next.title;

  // Lightbox: click right/left half or use arrow keys to move, esc to close.
  const box = document.getElementById("lightbox");
  const boxImg = document.getElementById("lightbox-img");
  const count = document.getElementById("count");
  document.getElementById("caption-title").textContent = project.title;
  let current = 0;

  function show(i) {
    current = (i + n) % n;
    boxImg.src = project.photos[current];
    boxImg.alt = `${project.title} ${current + 1}`;
    count.textContent = `${pad(current)} / ${String(n).padStart(2, "0")}`;
  }
  function openBox(i) {
    show(i);
    box.classList.add("open");
    document.body.style.overflow = "hidden";
  }
  function closeBox() {
    box.classList.remove("open");
    document.body.style.overflow = "";
  }

  document.getElementById("prev").addEventListener("click", () => show(current - 1));
  document.getElementById("next").addEventListener("click", () => show(current + 1));
  document.getElementById("close").addEventListener("click", closeBox);
  document.addEventListener("keydown", (e) => {
    if (!box.classList.contains("open")) return;
    if (e.key === "Escape") closeBox();
    if (e.key === "ArrowRight") show(current + 1);
    if (e.key === "ArrowLeft") show(current - 1);
  });
}
