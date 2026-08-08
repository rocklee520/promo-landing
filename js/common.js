window.Promo = (() => {
  function escapeHtml(str) {
    return String(str ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function escapeAttr(str) {
    return escapeHtml(str).replaceAll("'", "&#39;");
  }

  async function loadContent() {
    const res = await fetch(`/api/content?ts=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error("无法加载内容");
    return res.json();
  }

  function postHref(p) {
    if (p.gallery?.length || p.subtitle || p.series === "直播系列") {
      return `/post.html?id=${encodeURIComponent(p.id)}`;
    }
    if (p.link) return p.link;
    return `/post.html?id=${encodeURIComponent(p.id)}`;
  }

  function postTarget(p) {
    const href = postHref(p);
    return href.startsWith("http") ? "_blank" : "_self";
  }

  function searchPosts(posts, keyword) {
    const q = String(keyword || "").trim().toLowerCase();
    if (!q) return [];
    return posts.filter((p) => {
      const hay = [
        p.title,
        p.subtitle,
        p.summary,
        p.downloadNote,
        ...(p.tags || []),
        p.series,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }

  function bindSearchForm(form) {
    if (!form) return;
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const input = form.querySelector("input[name='keyword'], input[type='search']");
      const keyword = (input?.value || "").trim();
      if (!keyword) return;
      location.href = `/search.html?keyword=${encodeURIComponent(keyword)}`;
    });
  }

  function renderSiteChrome(data, { activeNav } = {}) {
    const site = data.site || {};
    const nameEl = document.getElementById("siteName");
    const subEl = document.getElementById("siteSub");
    const footEl = document.getElementById("siteFooter");
    if (nameEl) nameEl.textContent = site.name || "更新速递";
    if (subEl) subEl.textContent = site.subtitle || "";
    if (footEl) footEl.textContent = site.footer || "";
    document.title = document.title.includes("搜索")
      ? document.title
      : site.name || document.title;

    const nav = document.getElementById("mainNav");
    if (nav) {
      const items = data.nav?.length ? data.nav : ["全部", "直播系列"];
      nav.innerHTML = items
        .map((item) => {
          const href =
            item === "全部"
              ? "/"
              : `/?series=${encodeURIComponent(item)}`;
          const active =
            activeNav === item ||
            (!activeNav && item === "全部" && !new URLSearchParams(location.search).get("series"));
          return `<a class="nav-link ${active ? "active" : ""}" href="${href}">${escapeHtml(item)}</a>`;
        })
        .join("");
    }
  }

  return {
    escapeHtml,
    escapeAttr,
    loadContent,
    postHref,
    postTarget,
    searchPosts,
    bindSearchForm,
    renderSiteChrome,
  };
})();
