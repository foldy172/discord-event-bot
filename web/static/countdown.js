(function () {
  const pads = (n) => String(n).padStart(2, "0");

  function plural(n, one, few, many) {
    const mod10 = n % 10;
    const mod100 = n % 100;
    if (mod100 >= 11 && mod100 <= 14) return many;
    if (mod10 === 1) return one;
    if (mod10 >= 2 && mod10 <= 4) return few;
    return many;
  }

  function renderUnit(value, labels) {
    return `
      <div class="countdown-unit">
        <span class="countdown-value">${pads(value)}</span>
        <span class="countdown-label">${labels}</span>
      </div>`;
  }

  function initCountdown(el) {
    const unix = parseInt(el.dataset.unix, 10);
    const status = el.dataset.status || "pending";
    if (!unix) {
      el.innerHTML = '<p class="muted">Время не задано</p>';
      return;
    }

    const targetMs = unix * 1000;

    function tick() {
      const now = Date.now();
      const diff = targetMs - now;

      if (status === "ended" || status === "cancelled") {
        el.innerHTML = '<div class="countdown-message ended">Ивент завершён</div>';
        return;
      }
      if (status === "active" && diff <= 0) {
        el.innerHTML = '<div class="countdown-message active">Ивент идёт сейчас</div>';
        return;
      }
      if (diff <= 0) {
        el.innerHTML = '<div class="countdown-message active">Время наступило</div>';
        return;
      }

      const totalSec = Math.floor(diff / 1000);
      const days = Math.floor(totalSec / 86400);
      const hours = Math.floor((totalSec % 86400) / 3600);
      const minutes = Math.floor((totalSec % 3600) / 60);
      const seconds = totalSec % 60;

      let html = '<div class="countdown-grid">';
      if (days > 0) {
        html += renderUnit(
          days,
          plural(days, "день", "дня", "дней")
        );
      }
      html += renderUnit(hours, plural(hours, "час", "часа", "часов"));
      html += renderUnit(minutes, plural(minutes, "минута", "минуты", "минут"));
      html += renderUnit(seconds, plural(seconds, "секунда", "секунды", "секунд"));
      html += "</div>";
      html += '<p class="countdown-hint">до начала ивента</p>';
      el.innerHTML = html;
    }

    tick();
    setInterval(tick, 1000);
  }

  document.querySelectorAll(".countdown[data-unix]").forEach(initCountdown);
})();
