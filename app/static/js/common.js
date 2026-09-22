const API = (() => {
  async function request(url, options = {}) {
    const config = { ...options };
    config.headers = { ...(options.headers || {}) };
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
    const method = (config.method || "GET").toUpperCase();
    if (csrfToken && ["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
      config.headers["X-CSRF-Token"] = csrfToken;
    }
    if (config.body && !(config.body instanceof FormData)) {
      config.headers["Content-Type"] = "application/json";
    }
    try {
      const response = await fetch(url, config);
      if (response.status === 401 && !url.includes("/auth/login")) {
        window.location.href = "/login";
        return { ok: false, message: "请先登录" };
      }
      const data = await response.json();
      return data;
    } catch (error) {
      return { ok: false, message: `请求失败：${error.message}` };
    }
  }

  let toastTimer = null;
  function toast(message, type = "success") {
    const element = document.querySelector("[data-toast]");
    if (!element) return;
    element.textContent = message;
    element.className = `toast visible ${type}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      element.className = "toast";
    }, 2800);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  return { request, toast, escapeHtml };
})();

const navToggle = document.querySelector("[data-nav-toggle]");
if (navToggle) {
  navToggle.addEventListener("click", () => {
    document.querySelector("[data-main-nav]")?.classList.toggle("open");
  });
}

const navGroups = Array.from(document.querySelectorAll("[data-nav-group]"));

function closeNavGroups(except = null) {
  navGroups.forEach((group) => {
    if (group === except) return;
    group.classList.remove("open");
    group.querySelector("[data-nav-group-toggle]")?.setAttribute("aria-expanded", "false");
  });
}

navGroups.forEach((group) => {
  const toggle = group.querySelector("[data-nav-group-toggle]");
  if (!toggle) return;
  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    const shouldOpen = !group.classList.contains("open");
    closeNavGroups(group);
    group.classList.toggle("open", shouldOpen);
    toggle.setAttribute("aria-expanded", String(shouldOpen));
  });
});

document.addEventListener("click", (event) => {
  if (!event.target.closest("[data-nav-group]")) closeNavGroups();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeNavGroups();
    document.querySelector("[data-main-nav]")?.classList.remove("open");
  }
});

document.querySelectorAll("[data-main-nav] a").forEach((link) => {
  link.addEventListener("click", () => {
    closeNavGroups();
    document.querySelector("[data-main-nav]")?.classList.remove("open");
  });
});

document.querySelector("[data-logout]")?.addEventListener("click", async () => {
  await API.request("/api/auth/logout", { method: "POST" });
  window.location.href = "/login";
});
