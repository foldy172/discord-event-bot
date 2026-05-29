(function () {
  const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  document.querySelectorAll(".flash").forEach((el) => {
    el.classList.add("flash-visible");
    setTimeout(() => {
      el.classList.add("flash-hide");
      setTimeout(() => el.remove(), 400);
    }, 5000);
  });

  if (!prefersReduced) {
    document.querySelectorAll("[data-animate]").forEach((el, i) => {
      el.style.animationDelay = `${i * 0.06}s`;
      el.classList.add("animate-in");
    });
  }

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      const msg = form.getAttribute("data-confirm");
      if (msg && !window.confirm(msg)) {
        e.preventDefault();
      }
    });
  });
})();
