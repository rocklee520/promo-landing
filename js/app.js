(() => {
  const {
    escapeHtml,
    escapeAttr,
    titleWithPriceHtml,
    loadContent,
    postHref,
    postTarget,
    bindSearchForm,
    renderSiteChrome,
  } = window.Promo;

  const params = new URLSearchParams(location.search);
  const seriesParam = params.get("series") || "";

  const state = {
    data: null,
    activeTag: seriesParam || "全部",
    rankMode: "hot",
    sortMode: "newest",
    slide: 0,
    timer: null,
  };

  const els = {
    carouselTrack: document.getElementById("carouselTrack"),
    carouselDots: document.getElementById("carouselDots"),
    tagBar: document.getElementById("tagBar"),
    rankTabs: document.getElementById("rankTabs"),
    rankList: document.getElementById("rankList"),
    sortTabs: document.getElementById("sortTabs"),
    postList: document.getElementById("postList"),
    allTitle: document.getElementById("allTitle"),
  };

  bindSearchForm(document.getElementById("searchForm"));

  function posts() {
    return Array.isArray(state.data?.posts) ? state.data.posts.slice() : [];
  }

  function inSeries(p, series) {
    if (!series || series === "全部") return true;
    return p.series === series || (p.tags || []).includes(series);
  }

  function renderAll() {
    renderSiteChrome(state.data, { activeNav: seriesParam || "全部" });
    renderTags();
    renderCarousel();
    renderRank();
    renderPosts();
  }

  function renderTags() {
    const tags = state.data.tags?.length ? state.data.tags : ["全部"];
    if (!tags.includes("全部")) tags.unshift("全部");
    const navSeries = (state.data.nav || []).filter((n) => n && n !== "全部");
    for (const s of navSeries) {
      if (!tags.includes(s)) tags.splice(1, 0, s);
    }
    els.tagBar.innerHTML = tags
      .map(
        (tag) =>
          `<button class="tag ${tag === state.activeTag ? "active" : ""}" data-tag="${escapeAttr(tag)}">${escapeHtml(tag)}</button>`
      )
      .join("");
  }

  function featuredPosts() {
    // 轮播：最多 5 条，按浏览量从高到低
    const scoped = posts().filter((p) => inSeries(p, seriesParam));
    return scoped
      .slice()
      .sort((a, b) => {
        const dv = (b.views || 0) - (a.views || 0);
        if (dv) return dv;
        return String(b.date || "").localeCompare(String(a.date || ""));
      })
      .slice(0, 5);
  }

  function renderCarousel() {
    const list = featuredPosts();
    if (!list.length) {
      els.carouselTrack.innerHTML =
        '<div class="carousel-slide"><div class="carousel-caption"><h2>暂无轮播内容</h2></div></div>';
      els.carouselDots.innerHTML = "";
      return;
    }
    state.slide = Math.min(state.slide, list.length - 1);
    els.carouselTrack.innerHTML = list
      .map(
        (p) => `
        <a class="carousel-slide" href="${escapeAttr(postHref(p))}" target="${postTarget(p)}" rel="noopener noreferrer">
          <img src="${escapeAttr(p.cover || "")}" alt="${escapeAttr(p.title || "")}" loading="lazy" />
          <div class="carousel-caption"><h2>${titleWithPriceHtml(p)}</h2></div>
        </a>`
      )
      .join("");
    els.carouselDots.innerHTML = list
      .map(
        (_, i) =>
          `<button class="dot ${i === state.slide ? "active" : ""}" data-dot="${i}" aria-label="slide ${i + 1}"></button>`
      )
      .join("");
    els.carouselTrack.style.transform = `translateX(-${state.slide * 100}%)`;
    restartTimer(list.length);
  }

  function restartTimer(count) {
    if (state.timer) clearInterval(state.timer);
    if (count <= 1) return;
    state.timer = setInterval(() => {
      state.slide = (state.slide + 1) % count;
      els.carouselTrack.style.transform = `translateX(-${state.slide * 100}%)`;
      [...els.carouselDots.children].forEach((d, i) => d.classList.toggle("active", i === state.slide));
    }, 4500);
  }

  function rankedPosts() {
    // 热门推荐 / 最多浏览：都按真实浏览量排序
    let list = posts().filter((p) => inSeries(p, seriesParam));
    if (state.rankMode === "newest") {
      list.sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
    } else {
      list.sort((a, b) => {
        const dv = (b.views || 0) - (a.views || 0);
        if (dv !== 0) return dv;
        return String(b.date || "").localeCompare(String(a.date || ""));
      });
    }
    return list.slice(0, 8);
  }

  function renderRank() {
    const list = rankedPosts();
    if (!list.length) {
      els.rankList.innerHTML = '<div class="empty">暂无排行内容</div>';
      return;
    }
    els.rankList.innerHTML = list
      .map(
        (p, i) => `
        <a class="rank-item" href="${escapeAttr(postHref(p))}" target="${postTarget(p)}" rel="noopener noreferrer">
          <div class="rank-no">${String(i + 1).padStart(2, "0")}</div>
          <img src="${escapeAttr(p.cover || "")}" alt="" loading="lazy" />
          <div class="rank-meta">
            <h4>${titleWithPriceHtml(p)}</h4>
            <p>${escapeHtml((p.tags || []).slice(0, 2).join(" · ") || "未分类")} · ${Number(p.views || 0)} 浏览</p>
          </div>
        </a>`
      )
      .join("");
  }

  function filteredSortedPosts() {
    let list = posts().filter((p) => inSeries(p, seriesParam));
    if (state.activeTag && state.activeTag !== "全部") {
      list = list.filter(
        (p) =>
          (p.tags || []).includes(state.activeTag) ||
          p.series === state.activeTag
      );
    }
    if (state.sortMode === "oldest") {
      list.sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));
    } else if (state.sortMode === "views") {
      list.sort((a, b) => (b.views || 0) - (a.views || 0));
    } else {
      list.sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
    }
    return list;
  }

  function renderPosts() {
    const list = filteredSortedPosts();
    const label = seriesParam || (state.activeTag !== "全部" ? state.activeTag : "全部内容");
    els.allTitle.textContent = `${label}（${list.length}）`;
    if (!list.length) {
      els.postList.innerHTML = '<div class="empty">该分类下暂无内容</div>';
      return;
    }
    els.postList.innerHTML = list
      .map(
        (p) => `
        <a class="post-card" href="${escapeAttr(postHref(p))}" target="${postTarget(p)}" rel="noopener noreferrer">
          <div class="post-cover"><img src="${escapeAttr(p.cover || "")}" alt="" loading="lazy" /></div>
          <div class="post-body">
            <div class="post-tags">${(p.tags || []).map((t) => `<span class="pill">${escapeHtml(t)}</span>`).join("")}</div>
            <h3>${titleWithPriceHtml(p)}</h3>
            <p class="post-summary">${escapeHtml(p.subtitle || p.summary || "")}</p>
            <div class="post-foot"><span>${escapeHtml(p.date || "")}</span><span>${Number(p.views || 0)} 浏览</span></div>
          </div>
        </a>`
      )
      .join("");
  }

  els.tagBar.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-tag]");
    if (!btn) return;
    const tag = btn.dataset.tag;
    const navSeries = new Set((state.data?.nav || []).filter((n) => n && n !== "全部"));
    if (navSeries.has(tag)) {
      location.href = `/?series=${encodeURIComponent(tag)}`;
      return;
    }
    if (seriesParam && tag === "全部") {
      location.href = "/";
      return;
    }
    state.activeTag = tag;
    renderTags();
    renderPosts();
  });

  els.rankTabs.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-rank]");
    if (!btn) return;
    state.rankMode = btn.dataset.rank;
    [...els.rankTabs.children].forEach((el) => el.classList.toggle("active", el === btn));
    renderRank();
  });

  els.sortTabs.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-sort]");
    if (!btn) return;
    state.sortMode = btn.dataset.sort;
    [...els.sortTabs.children].forEach((el) => el.classList.toggle("active", el === btn));
    renderPosts();
  });

  els.carouselDots.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-dot]");
    if (!btn) return;
    state.slide = Number(btn.dataset.dot) || 0;
    renderCarousel();
  });

  loadContent()
    .then((data) => {
      state.data = data;
      if (seriesParam) state.activeTag = seriesParam;
      renderAll();
    })
    .catch((err) => {
      document.body.insertAdjacentHTML(
        "beforeend",
        `<div class="wrap empty" style="margin:24px auto;">加载失败：${escapeHtml(err.message)}。请先运行 server.py 再访问。</div>`
      );
    });
})();
