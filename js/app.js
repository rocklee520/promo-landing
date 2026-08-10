(() => {
  const {
    escapeHtml,
    escapeAttr,
    titleWithPriceHtml,
    thumbUrl,
    coverUrl,
    compareNewest,
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
    rankMode: "hot",
    sortMode: "newest",
    slide: 0,
    timer: null,
  };

  const els = {
    carouselTrack: document.getElementById("carouselTrack"),
    carouselDots: document.getElementById("carouselDots"),
    rankTabs: document.getElementById("rankTabs"),
    rankList: document.getElementById("rankList"),
    sortTabs: document.getElementById("sortTabs"),
    postList: document.getElementById("postList"),
    allTitle: document.getElementById("allTitle"),
  };

  bindSearchForm(document.getElementById("searchForm"));

  function posts() {
    return window.Promo.publicPosts(state.data?.posts);
  }

  function inSeries(p, series) {
    if (!series || series === "全部") return true;
    return p.series === series || (p.tags || []).includes(series);
  }

  function renderAll() {
    renderSiteChrome(state.data, { activeNav: seriesParam || "全部" });
    renderCarousel();
    renderRank();
    renderPosts();
  }

  function featuredPosts() {
    // 轮播：最新上架封面（按 updatedAt / date）
    const scoped = posts().filter((p) => inSeries(p, seriesParam) && p.cover);
    return scoped.slice().sort(compareNewest).slice(0, 5);
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
        (p, i) => `
        <a class="carousel-slide" href="${escapeAttr(postHref(p))}" target="${postTarget(p)}" rel="noopener noreferrer">
          <img src="${escapeAttr(coverUrl(p, 720))}" alt="${escapeAttr(p.title || "")}" ${i === 0 ? 'fetchpriority="high"' : 'loading="lazy"'} decoding="async" />
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

  function extractSize(p) {
    const hay = [p.subtitle, p.summary, p.title].filter(Boolean).join(" ");
    const m = hay.match(/(\d+(?:\.\d+)?)\s*([GgTt])[Bb]?/);
    if (!m) return "";
    const unit = m[2].toUpperCase() === "T" ? "TB" : "GB";
    return `${m[1]}${unit}`;
  }

  function rankedPosts() {
    // 热门排行：按真实浏览量
    let list = posts().filter((p) => inSeries(p, seriesParam));
    if (state.rankMode === "newest") {
      list.sort(compareNewest);
    } else {
      list.sort((a, b) => {
        const dv = (b.views || 0) - (a.views || 0);
        if (dv !== 0) return dv;
        return compareNewest(a, b);
      });
    }
    return list.slice(0, 12);
  }

  function renderRank() {
    const list = rankedPosts();
    if (!list.length) {
      els.rankList.innerHTML = '<div class="empty">暂无排行内容</div>';
      return;
    }
    const eye = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 5c-5 0-9.3 3.1-11 7 1.7 3.9 6 7 11 7s9.3-3.1 11-7c-1.7-3.9-6-7-11-7zm0 12a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"/></svg>`;
    els.rankList.innerHTML = list
      .map((p) => {
        const size = extractSize(p);
        return `
        <a class="rank-card" href="${escapeAttr(postHref(p))}" target="${postTarget(p)}" rel="noopener noreferrer">
          <div class="rank-card-cover"><img src="${escapeAttr(coverUrl(p, 360))}" alt="" loading="lazy" decoding="async" /></div>
          <div class="rank-card-body">
            <h4>${titleWithPriceHtml(p)}</h4>
            <div class="rank-card-meta">
              <span class="views">${eye}${Number(p.views || 0)}</span>
              ${size ? `<span>${escapeHtml(size)}</span>` : `<span></span>`}
            </div>
          </div>
        </a>`;
      })
      .join("");
  }

  function filteredSortedPosts() {
    const list = posts().filter((p) => inSeries(p, seriesParam));
    if (state.sortMode === "oldest") {
      list.sort((a, b) => compareNewest(b, a));
    } else if (state.sortMode === "views") {
      list.sort((a, b) => {
        const dv = (b.views || 0) - (a.views || 0);
        if (dv !== 0) return dv;
        return compareNewest(a, b);
      });
    } else {
      list.sort(compareNewest);
    }
    return list;
  }

  function renderPosts() {
    const list = filteredSortedPosts();
    const label = seriesParam || "全部内容";
    els.allTitle.textContent = `${label}（${list.length}）`;
    if (!list.length) {
      els.postList.innerHTML = '<div class="empty">该分类下暂无内容</div>';
      return;
    }
    els.postList.innerHTML = list
      .map((p) => {
        const size = extractSize(p);
        return `
        <a class="post-card" href="${escapeAttr(postHref(p))}" target="${postTarget(p)}" rel="noopener noreferrer">
          <div class="post-cover"><img src="${escapeAttr(coverUrl(p, 360))}" alt="" loading="lazy" decoding="async" /></div>
          <div class="post-body">
            <h3>${titleWithPriceHtml(p)}</h3>
            <p class="post-summary">${escapeHtml(p.subtitle || p.summary || "")}</p>
            <div class="post-foot">
              <span>${Number(p.views || 0)} 浏览</span>
              <span>${size ? escapeHtml(size) : escapeHtml(p.date || "")}</span>
            </div>
          </div>
        </a>`;
      })
      .join("");
  }

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

  loadContent({ lite: true })
    .then((data) => {
      state.data = data;
      renderAll();
    })
    .catch((err) => {
      document.body.insertAdjacentHTML(
        "beforeend",
        `<div class="wrap empty" style="margin:24px auto;">加载失败：${escapeHtml(err.message)}。请先运行 server.py 再访问。</div>`
      );
    });
})();
