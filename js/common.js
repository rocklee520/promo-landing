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

  /** Prefer prebuilt static list thumbs (fast). Fall back to /img, then original. */
  function staticListThumb(src, width = 360) {
    const s = String(src || "").trim();
    if (!s.startsWith("/assets/")) return "";
    const w = Number(width) || 360;
    const bucket = w <= 240 ? 240 : 360;
    return `/thumbs/list/${bucket}${s}.webp`;
  }

  /** Serve resized WebP via static thumb or /img. Keep animated covers intact on detail. */
  function thumbUrl(src, width = 480) {
    const s = String(src || "").trim();
    if (!s) return "";
    if (!s.startsWith("/assets/")) return s;
    // GIF / dedicated animated cover files must not be freeze-framed by /img on detail
    if (/\.gif(?:$|\?)/i.test(s) || /\/cover\.(gif|webp)(?:$|\?)/i.test(s)) return s;
    const w = Number(width) || 480;
    const pre = staticListThumb(s, w <= 360 ? w : 360);
    if (pre && w <= 360) return pre;
    return `/img?u=${encodeURIComponent(s)}&w=${w}`;
  }

  /** List/card cover: always prefer tiny static WebP (even for GIF covers). */
  function coverUrl(p, width = 360) {
    const cover = String(p?.cover || "").trim();
    const gallery = Array.isArray(p?.gallery) ? p.gallery : [];
    const animated = gallery.find((u) =>
      /\.(gif)(?:$|\?)/i.test(String(u || "")) ||
      /\/cover\.(gif|webp)(?:$|\?)/i.test(String(u || ""))
    );
    const coverIsAnimated =
      /\.gif(?:$|\?)/i.test(cover) || /\/cover\.(gif|webp)(?:$|\?)/i.test(cover);
    const src = (!coverIsAnimated && animated ? animated : cover) || cover;
    const w = Number(width) || 360;
    const pre = staticListThumb(src, w);
    if (pre) return pre;
    // Animated full GIF only as last resort for list (slow) — still try /img for stills
    if (coverIsAnimated || /\.gif(?:$|\?)/i.test(String(src || ""))) {
      return staticListThumb(cover, w) || cover;
    }
    return thumbUrl(src, w);
  }

  /** img onerror: static thumb -> /img -> original asset */
  function bindImgFallback(root) {
    if (!root) return;
    root.querySelectorAll("img[data-full], img[src*='/thumbs/list/']").forEach((img) => {
      if (img.dataset.fbBound) return;
      img.dataset.fbBound = "1";
      img.addEventListener("error", () => {
        const full = img.getAttribute("data-full") || "";
        const src = img.getAttribute("src") || "";
        const step = Number(img.dataset.fbStep || "0");
        if (step === 0 && src.includes("/thumbs/list/")) {
          img.dataset.fbStep = "1";
          // Extract /assets/... from /thumbs/list/360/assets/....webp
          const m = src.match(/\/thumbs\/list\/\d+(\/assets\/.+?)\.webp(?:$|\?)/i);
          const asset = full || (m ? m[1] : "");
          if (asset) {
            img.src = `/img?u=${encodeURIComponent(asset)}&w=360`;
            return;
          }
        }
        if (step <= 1) {
          img.dataset.fbStep = "2";
          const m = src.match(/\/thumbs\/list\/\d+(\/assets\/.+?)\.webp(?:$|\?)/i);
          const asset = full || (m ? m[1] : "");
          if (asset) img.src = asset;
        }
      });
    });
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
    const name = site.name || "小米素材站";
    const sub = site.subtitle || "";
    const nameEl = document.getElementById("siteName");
    const subEl = document.getElementById("siteSub");
    const footEl = document.getElementById("siteFooter");
    const heroName = document.getElementById("heroSiteName");
    const heroSub = document.getElementById("heroSiteSub");
    const footerName = document.getElementById("footerName");
    const footerSub = document.getElementById("footerSub");
    if (nameEl) nameEl.textContent = name;
    if (subEl) subEl.textContent = sub;
    if (heroName) heroName.textContent = name;
    if (heroSub) heroSub.textContent = sub || "稀有精品预览";
    if (footerName) footerName.textContent = name;
    if (footerSub) footerSub.textContent = sub || "素材预览";
    if (footEl) footEl.textContent = site.footer || "";
    document.title = document.title.includes("搜索")
      ? document.title
      : name || document.title;

    const nav = document.getElementById("mainNav");
    if (nav) {
      // No series classification — top nav is home only (baseline-style keyword search).
      const onHome = location.pathname === "/" || location.pathname.endsWith("/index.html");
      nav.innerHTML = `<a class="nav-link ${onHome ? "active" : ""}" href="/">首页</a>`;
    }
  }

  return {
    escapeHtml,
    escapeAttr,
    formatPrice,
    thumbUrl,
    coverUrl,
    bindImgFallback,
    staticListThumb,
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
