(() => {
  const { escapeHtml, escapeAttr, loadContent, bindSearchForm, renderSiteChrome } = window.Promo;
  const params = new URLSearchParams(location.search);
  const id = params.get("id");
  const root = document.getElementById("noteArticle");

  bindSearchForm(document.getElementById("searchForm"));

  function renderPost(p) {
    document.title = p.title || "详情";
    const gallery = Array.isArray(p.gallery) ? p.gallery : [];
    const linkBlock = p.link
      ? `<p class="note-download-link"><a href="${escapeAttr(p.link)}" target="_blank" rel="noopener noreferrer">打开下载 / 资源链接</a></p>`
      : "";

    root.innerHTML = `
      <div class="note-inline-title">${escapeHtml(p.title || "")}</div>
      ${p.subtitle ? `<h1 class="note-h1">${escapeHtml(p.subtitle)}</h1>` : ""}
      <h1 class="note-h1">内容简介</h1>
      <p class="note-p"><strong>${escapeHtml(p.summary || "")}</strong></p>
      ${p.downloadNote ? `<p class="note-p note-download-note">${escapeHtml(p.downloadNote)}</p>` : ""}
      ${linkBlock}
      <div class="note-gallery">
        ${gallery
          .map(
            (src) =>
              `<p class="note-img-wrap"><img src="${escapeAttr(src)}" alt="" loading="lazy" /></p>`
          )
          .join("")}
      </div>
      <h1 class="note-h1">内容图集预览</h1>
      <div class="note-meta">
        <span>${escapeHtml(p.date || "")}</span>
        <span>${Number(p.views || 0)} 浏览</span>
        <span>${escapeHtml((p.tags || []).join(" · "))}</span>
      </div>
    `;
  }

  loadContent()
    .then((data) => {
      renderSiteChrome(data, { activeNav: "直播系列" });
      const post = (data.posts || []).find((p) => p.id === id);
      if (!post) {
        root.innerHTML = `<div class="empty">未找到内容。<a href="/">返回首页</a></div>`;
        return;
      }
      renderPost(post);
    })
    .catch((err) => {
      root.innerHTML = `<div class="empty">加载失败：${escapeHtml(err.message)}</div>`;
    });
})();
