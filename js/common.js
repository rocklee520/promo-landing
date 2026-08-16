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

  /** Prefer updatedAt (上架/改价时间), fall back to date. */
  function postTime(p) {
    return String(p?.updatedAt || p?.date || "");
  }

  function compareNewest(a, b) {
    const d = postTime(b).localeCompare(postTime(a));
    if (d) return d;
    return String(b?.date || "").localeCompare(String(a?.date || ""));
  }

  /** Serve resized WebP via /img. Keep animated covers intact. */
  function thumbUrl(src, width = 480) {
    const s = String(src || "").trim();
    if (!s) return "";
    if (!s.startsWith("/assets/")) return s;
    // GIF / dedicated animated cover files must not be freeze-framed by /img
    if (/\.gif(?:$|\?)/i.test(s) || /\/cover\.(gif|webp)(?:$|\?)/i.test(s)) return s;
    const w = Number(width) || 480;
    return `/img?u=${encodeURIComponent(s)}&w=${w}`;
  }

  /** Prefer animated cover (GIF / cover.webp) when available. */
  function coverUrl(p, width = 480) {
    const cover = String(p?.cover || "").trim();
    const gallery = Array.isArray(p?.gallery) ? p.gallery : [];
    const animated = gallery.find((u) =>
      /\.(gif)(?:$|\?)/i.test(String(u || "")) ||
      /\/cover\.(gif|webp)(?:$|\?)/i.test(String(u || ""))
    );
    const coverIsAnimated =
      /\.gif(?:$|\?)/i.test(cover) || /\/cover\.(gif|webp)(?:$|\?)/i.test(cover);
    const src = (!coverIsAnimated && animated ? animated : cover) || cover;
    return thumbUrl(src, width);
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
    const cacheKey = lite ? "promo_content_lite_v3" : "promo_content_full_v3";
    const ttlMs = lite ? 30_000 : 15_000;
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

  const DEFAULT_HOT_KEYWORDS = [
    "合集",
    "自慰",
    "福利姬",
    "反差",
    "女神",
    "推特",
    "白虎",
    "萝莉",
  ];

  function hotKeywords(data) {
    const fromSite = data?.site?.hotKeywords;
    if (Array.isArray(fromSite) && fromSite.length) {
      return fromSite.map((s) => String(s || "").trim()).filter(Boolean);
    }
    return DEFAULT_HOT_KEYWORDS.slice();
  }

  function renderHotKeywords(data, container, { active } = {}) {
    if (!container) return;
    const words = hotKeywords(data);
    if (!words.length) {
      container.innerHTML = "";
      container.hidden = true;
      return;
    }
    container.hidden = false;
    const activeWord = String(active || "").trim();
    container.innerHTML = `
      <span class="hot-keywords-label">搜索热词</span>
      <div class="hot-keywords-list">
        ${words
          .map((w) => {
            const on = activeWord && activeWord === w;
            return `<a class="hot-keyword ${on ? "active" : ""}" href="/search.html?keyword=${encodeURIComponent(w)}">${escapeHtml(w)}</a>`;
          })
          .join("")}
      </div>`;
  }

  function searchPosts(posts, keyword) {
    const q = String(keyword || "").trim().toLowerCase();
    if (!q) return [];
    return publicPosts(posts).filter((p) => {
      const hay = [
        p.id,
        p.title,
        p.subtitle,
        p.summary,
        p.price,
        p.downloadNote,
        ...(p.tags || []),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }

  function bindSearchForm(form) {
    if (!form) return;
    // Prefer native GET submit (works on mobile WebViews). Only enhance Enter key.
    form.setAttribute("action", form.getAttribute("action") || "/search.html");
    form.setAttribute("method", "get");
    const input = form.querySelector("input[name='keyword'], input[type='search']");
    if (input) {
      input.setAttribute("enterkeyhint", "search");
      input.setAttribute("autocapitalize", "off");
      input.setAttribute("autocomplete", "off");
      input.setAttribute("spellcheck", "false");
      // iOS Safari: avoid zoom-on-focus without tiny text
      if (!input.style.fontSize) input.style.fontSize = "16px";
    }
    form.addEventListener("submit", (e) => {
      const el = form.querySelector("input[name='keyword'], input[type='search']");
      const keyword = (el?.value || "").trim();
      if (!keyword) {
        e.preventDefault();
        el?.focus();
        return;
      }
      // Keep value trimmed in the query string
      if (el && el.value !== keyword) el.value = keyword;
      // Do NOT preventDefault — native navigation is more reliable on phones
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
      // No series classification — top nav is home only (baseline-style keyword search).
      const onHome = location.pathname === "/" || location.pathname.endsWith("/index.html");
      nav.innerHTML = `<a class="nav-link ${onHome ? "active" : ""}" href="/">全部</a>`;
    }
  }

  return {
    escapeHtml,
    escapeAttr,
    formatPrice,
    thumbUrl,
    coverUrl,
    postTime,
    compareNewest,
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
    hotKeywords,
    renderHotKeywords,
    DEFAULT_HOT_KEYWORDS,
  };
})();
