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

  function formatPrice(price) {
    const s = String(price ?? "").trim();
    if (!s) return "";
    return /元|￥|\$|¥/.test(s) ? s : `${s}元`;
  }

  /** Serve resized WebP via /img (falls back to original for remote URLs). */
  function thumbUrl(src, width = 480) {
    const s = String(src || "").trim();
    if (!s) return "";
    if (!s.startsWith("/assets/")) return s;
    const w = Number(width) || 480;
    return `/img?u=${encodeURIComponent(s)}&w=${w}`;
  }

  /** Safe HTML: title + optional price badge */
  function titleWithPriceHtml(p) {
    const title = escapeHtml(p?.title || "");
    const price = formatPrice(p?.price);
    if (!price) return title;
    return `${title} <span class="price-tag">${escapeHtml(price)}</span>`;
  }

  async function loadContent(options = {}) {
    const lite = Boolean(options.lite);
    const cacheKey = lite ? "promo_content_lite_v1" : "promo_content_full_v1";
    const ttlMs = lite ? 60_000 : 30_000;
    try {
      const cached = sessionStorage.getItem(cacheKey);
      if (cached) {
        const parsed = JSON.parse(cached);
        if (parsed && parsed._ts && Date.now() - parsed._ts < ttlMs && parsed.data) {
          return parsed.data;
        }
      }
    } catch {
      /* ignore */
    }
    const q = lite ? "lite=1" : "";
    const res = await fetch(`/api/content?${q}`, { cache: lite ? "default" : "no-store" });
    if (!res.ok) throw new Error("无法加载内容");
    const data = await res.json();
    try {
      sessionStorage.setItem(cacheKey, JSON.stringify({ _ts: Date.now(), data }));
    } catch {
      /* ignore quota */
    }
    return data;
  }

  /** Record a real page view (server-side, 6h cooldown per visitor per post). */
  async function trackView(postId) {
    if (!postId) return null;
    const key = `viewed:${postId}`;
    try {
      if (sessionStorage.getItem(key)) return null;
    } catch {
      /* ignore */
    }
    try {
      const res = await fetch("/api/view", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ id: postId }),
      });
      if (!res.ok) return null;
      const data = await res.json();
      try {
        sessionStorage.setItem(key, "1");
      } catch {
        /* ignore */
      }
      return data;
    } catch {
      return null;
    }
  }

  function postHref(p) {
    if (p.gallery?.length || p.galleryCount || p.subtitle || p.series) {
      return `/post.html?id=${encodeURIComponent(p.id)}`;
    }
    if (p.link) return p.link;
    return `/post.html?id=${encodeURIComponent(p.id)}`;
  }

  function postTarget(p) {
    const href = postHref(p);
    return href.startsWith("http") ? "_blank" : "_self";
  }

  function isPublicPost(p) {
    return Boolean(p) && !p.hidden;
  }

  function publicPosts(posts) {
    return (Array.isArray(posts) ? posts : []).filter(isPublicPost);
  }

  function searchPosts(posts, keyword) {
    const q = String(keyword || "").trim().toLowerCase();
    if (!q) return [];
    return publicPosts(posts).filter((p) => {
      const hay = [
        p.title,
        p.subtitle,
        p.summary,
        p.price,
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
    if (nameEl) nameEl.textContent = site.name || "小米素材站";
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
    formatPrice,
    thumbUrl,
    titleWithPriceHtml,
    loadContent,
    trackView,
    postHref,
    postTarget,
    isPublicPost,
    publicPosts,
    searchPosts,
    bindSearchForm,
    renderSiteChrome,
  };
})();
