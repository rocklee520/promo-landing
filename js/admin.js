(() => {
  const AUTH_KEY = "promo_admin_authed";
  let data = null;
  let password = sessionStorage.getItem(AUTH_KEY) || "";

  const $ = (id) => document.getElementById(id);
  const toastEl = $("toast");

  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    setTimeout(() => toastEl.classList.remove("show"), 2200);
  }

  async function fetchContent() {
    const res = await fetch(`/api/content?ts=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error("加载失败，请确认已启动 server.py");
    data = await res.json();
    ensureShape();
  }

  function ensureShape() {
    data.site ||= {
      name: "更新速递",
      subtitle: "最新视频 / 图片预览与介绍",
      footer: "",
      adminPassword: "admin123",
    };
    data.tags ||= ["全部", "直播系列", "最新", "热门", "视频", "图片"];
    data.nav ||= ["全部", "直播系列", "最新", "热门"];
    data.posts ||= [];
  }

  function showEditor() {
    $("loginCard").hidden = true;
    $("editor").hidden = false;
    $("cfgName").value = data.site.name || "";
    $("cfgSub").value = data.site.subtitle || "";
    $("cfgFooter").value = data.site.footer || "";
    $("cfgPassword").value = data.site.adminPassword || "";
    $("cfgTags").value = (data.tags || []).join(",");
    if (!$("editDate").value) $("editDate").value = new Date().toISOString().slice(0, 10);
    renderList();
    $("saveHint").textContent =
      "保存后会写入 data/content.json，前台刷新即可看到。公网部署后同样通过此后台修改。";
  }

  function renderList() {
    const list = data.posts
      .slice()
      .sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
    $("adminList").innerHTML = list.length
      ? list
          .map(
            (p) => `
        <div class="admin-post" data-id="${escapeAttr(p.id)}">
          <img src="${escapeAttr(p.cover || "")}" alt="" />
          <div>
            <h4>${escapeHtml(p.title || "未命名")}</h4>
            <p>${escapeHtml((p.tags || []).join(" / "))} · ${escapeHtml(p.date || "")} · ${Number(p.views || 0)} 浏览</p>
          </div>
          <div class="admin-actions">
            <button class="btn" data-act="edit">编辑</button>
            <button class="btn" data-act="up">上移</button>
            <button class="btn" data-act="down">下移</button>
            <button class="btn" data-act="del">删除</button>
          </div>
        </div>`
          )
          .join("")
      : '<p class="muted">还没有内容，先在上方表单添加一条。</p>';
  }

  function readSiteForm() {
    data.site.name = $("cfgName").value.trim() || "更新速递";
    data.site.subtitle = $("cfgSub").value.trim();
    data.site.footer = $("cfgFooter").value.trim();
    data.site.adminPassword = $("cfgPassword").value.trim() || data.site.adminPassword || "admin123";
    data.tags = $("cfgTags").value
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!data.tags.includes("全部")) data.tags.unshift("全部");
  }

  function flagsFromSelect(v) {
    return {
      featured: v === "featured" || v === "both",
      hot: v === "hot" || v === "both",
    };
  }

  function selectFromFlags(p) {
    if (p.featured && p.hot) return "both";
    if (p.featured) return "featured";
    if (p.hot) return "hot";
    return "none";
  }

  function fillForm(p) {
    $("editId").value = p.id || "";
    $("editTitle").value = p.title || "";
    $("editSubtitle").value = p.subtitle || "";
    $("editCover").value = p.cover || "";
    $("editSummary").value = p.summary || "";
    $("editDownloadNote").value = p.downloadNote || "";
    $("editLink").value = p.link || "";
    $("editGallery").value = (p.gallery || []).join("\n");
    $("editSeries").value = p.series || "";
    $("editTags").value = (p.tags || []).join(",");
    $("editDate").value = p.date || new Date().toISOString().slice(0, 10);
    $("editViews").value = Number(p.views || 0);
    $("editFlags").value = selectFromFlags(p);
  }

  function resetForm() {
    $("editId").value = "";
    $("editTitle").value = "";
    $("editSubtitle").value = "";
    $("editCover").value = "";
    $("editSummary").value = "";
    $("editDownloadNote").value = "";
    $("editLink").value = "";
    $("editGallery").value = "";
    $("editSeries").value = "";
    $("editTags").value = "";
    $("editDate").value = new Date().toISOString().slice(0, 10);
    $("editViews").value = "0";
    $("editFlags").value = "none";
  }

  function upsertFromForm() {
    const title = $("editTitle").value.trim();
    if (!title) return toast("请填写标题");
    const flags = flagsFromSelect($("editFlags").value);
    const id = $("editId").value || `post-${Date.now()}`;
    const series = $("editSeries").value.trim();
    let tags = $("editTags").value
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (series && !tags.includes(series)) tags = [series, ...tags];
    const existing = data.posts.find((p) => p.id === id) || {};
    const item = {
      ...existing,
      id,
      title,
      subtitle: $("editSubtitle").value.trim(),
      cover: $("editCover").value.trim(),
      summary: $("editSummary").value.trim(),
      downloadNote: $("editDownloadNote").value.trim(),
      link: $("editLink").value.trim(),
      gallery: $("editGallery").value
        .split(/\r?\n/)
        .map((s) => s.trim())
        .filter(Boolean),
      series,
      tags,
      date: $("editDate").value || new Date().toISOString().slice(0, 10),
      views: Number($("editViews").value || 0),
      featured: flags.featured,
      hot: flags.hot,
    };
    const idx = data.posts.findIndex((p) => p.id === id);
    if (idx >= 0) data.posts[idx] = item;
    else data.posts.unshift(item);
    resetForm();
    renderList();
    toast(idx >= 0 ? "已更新到列表，记得点保存" : "已加入列表，记得点保存");
  }

  function downloadBackup(payload, filename) {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function saveAll() {
    readSiteForm();
    const res = await fetch("/api/content", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Password": password,
      },
      body: JSON.stringify(data),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || "保存失败");
    data = body.content || data;
    password = data.site.adminPassword;
    sessionStorage.setItem(AUTH_KEY, password);
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadBackup(data, `content-backup-${stamp}.json`);
    toast("已保存，并已下载本地备份");
    renderList();
  }

  function exportJson() {
    readSiteForm();
    downloadBackup(data, "content.json");
  }

  async function tryLogin() {
    password = $("passwordInput").value.trim();
    await fetchContent();
    if (password !== (data.site.adminPassword || "admin123")) {
      toast("密码错误");
      return;
    }
    sessionStorage.setItem(AUTH_KEY, password);
    showEditor();
  }

  function escapeHtml(str) {
    return String(str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function escapeAttr(str) {
    return escapeHtml(str).replaceAll("'", "&#39;");
  }

  $("loginBtn").addEventListener("click", () => {
    tryLogin().catch((e) => toast(e.message));
  });
  $("passwordInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") tryLogin().catch((err) => toast(err.message));
  });
  $("upsertBtn").addEventListener("click", upsertFromForm);
  $("resetFormBtn").addEventListener("click", resetForm);
  $("saveAllBtn").addEventListener("click", () => {
    saveAll().catch((e) => toast(e.message));
  });
  $("exportBtn").addEventListener("click", exportJson);
  $("logoutBtn").addEventListener("click", () => {
    sessionStorage.removeItem(AUTH_KEY);
    location.reload();
  });
  $("importInput").addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      data = JSON.parse(text);
      ensureShape();
      showEditor();
      toast("已导入，记得保存到服务器");
    } catch {
      toast("JSON 无效");
    } finally {
      e.target.value = "";
    }
  });

  $("adminList").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-act]");
    const row = e.target.closest("[data-id]");
    if (!btn || !row) return;
    const id = row.dataset.id;
    const idx = data.posts.findIndex((p) => p.id === id);
    if (idx < 0) return;
    const act = btn.dataset.act;
    if (act === "edit") {
      fillForm(data.posts[idx]);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else if (act === "del") {
      if (confirm("确定删除这条？")) {
        data.posts.splice(idx, 1);
        renderList();
        toast("已从列表删除，记得保存");
      }
    } else if (act === "up" && idx > 0) {
      const t = data.posts[idx - 1];
      data.posts[idx - 1] = data.posts[idx];
      data.posts[idx] = t;
      renderList();
    } else if (act === "down" && idx < data.posts.length - 1) {
      const t = data.posts[idx + 1];
      data.posts[idx + 1] = data.posts[idx];
      data.posts[idx] = t;
      renderList();
    }
  });

  if (password) {
    fetchContent()
      .then(() => {
        if (password === (data.site.adminPassword || "admin123")) showEditor();
        else sessionStorage.removeItem(AUTH_KEY);
      })
      .catch(() => {});
  }
})();
