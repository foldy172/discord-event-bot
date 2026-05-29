(function () {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  const orbs = document.querySelector(".cyber-orbs");
  if (!orbs) return;

  let mx = 0.5;
  let my = 0.5;
  document.addEventListener("mousemove", (e) => {
    mx = e.clientX / window.innerWidth;
    my = e.clientY / window.innerHeight;
    orbs.style.setProperty("--mx", String(mx));
    orbs.style.setProperty("--my", String(my));
  });
})();
