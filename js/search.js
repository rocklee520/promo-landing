(() => {
  const {
    escapeHtml,
    escapeAttr,
    titleWithPriceHtml,
    thumbUrl,
    coverUrl,
    loadContent,
    searchPosts,
    postHref,
    postTarget,
    bindSearchForm,
    renderSiteChrome,
  } = window.Promo;

  const params = new URLSearchParams(location.search);
  const keyword = (params.get("keyword") || "").trim();
  const heading = document.getElementById("searchHeading");
  const countEl = document.getElementById("searchCount");
  const grid = document.getElementById("searchGrid");
  const empty = document.getElementById("searchEmpty");
  const input = document.getElementById("searchInput");

  if (input) input.value = keyword;
  bindSearchForm(document.getElementById("searchForm"));
  document.title = keyword ? `搜索：${keyword}` : "搜索";
  heading.innerHTML = keyword
    ? `搜索： <span>${escapeHtml(keyword)}</span>`
    : "搜索";

  loadContent({ lite: true })
    .then((data) => {
      renderSiteChrome(data, { activeNav: null });
      window.Promo.renderHotKeywords(data, document.getElementById("hotKeywords"), {
        active: keyword,
      });
      if (!keyword) {
        countEl.textContent = "点击上方热词，或输入关键词搜索";
        empty.hidden = true;
        empty.style.display = "none";
        grid.innerHTML = "";
        return;
      }
      const results = searchPosts(data.posts || [], keyword);
      countEl.textContent = `找到 ${results.length} 个结果`;
      if (!results.length) {
        grid.innerHTML = "";
        empty.hidden = false;
        empty.style.display = "";
        return;
      }
      empty.hidden = true;
      empty.style.display = "none";
      grid.innerHTML = results
        .map(
          (p) => `
        <a class="search-card" href="${escapeAttr(postHref(p))}" target="${postTarget(p)}" rel="noopener noreferrer">
          <div class="search-cover"><img src="${escapeAttr(coverUrl(p, 240))}" data-full="${escapeAttr(p.cover || "")}" alt="" loading="lazy" decoding="async" /></div>
          <div class="search-card-body">
            <h3>${titleWithPriceHtml(p)}</h3>
            <p>${escapeHtml(p.subtitle || p.summary || "")}</p>
            <div class="post-foot">
              <span>${escapeHtml(p.date || "")}</span>
              <span>${Number(p.views || 0)} 浏览</span>
            </div>
          </div>
        </a>`
        )
        .join("");
      window.Promo.bindImgFallback(grid);
    })
    .catch((err) => {
      countEl.textContent = `加载失败：${err.message}`;
    });
})();
