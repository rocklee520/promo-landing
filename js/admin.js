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
    const res = await fetch(`/api/content?ts=${Date.now()}`, {
      cache: "no-store",
      headers: password ? { "X-Admin-Password": password } : {},
    });
    if (!res.ok) throw new Error("加载失败，请确认已启动 server.py");
    data = await res.json();
    ensureShape();
  }

  function ensureShape() {
    data.site ||= {
      name: "小米素材站",
      subtitle: "最新视频 / 图片预览与介绍",
      footer: "",
      adminPassword: "admin123",
    };
    data.site.pay ||= {
      wechatQr: "",
      alipayQr: "",
      note: "付款时请在备注/说明里填写订单号，付完回到本页点「我已付款」。",
      pushPlusToken: "",
    };
    data.tags ||= ["全部", "直播系列", "网红系列", "机构系列", "岛国系列", "TP系列", "视频", "图片"];
    data.nav ||= ["全部", "直播系列", "网红系列", "机构系列", "岛国系列", "TP系列"];
    data.posts ||= [];
  }

  function showEditor() {
    $("loginCard").hidden = true;
    $("editor").hidden = false;
    $("cfgName").value = data.site.name || "";
    $("cfgSub").value = data.site.subtitle || "";
    $("cfgFooter").value = data.site.footer || "";
    $("cfgPassword").value = "";
    $("cfgPassword").placeholder = "留空则不修改密码";
    $("cfgTags").value = (data.tags || []).join(",");
    const pay = data.site.pay || {};
    $("cfgWechatQr").value = pay.wechatQr || "";
    $("cfgAlipayQr").value = pay.alipayQr || "";
    $("cfgPayNote").value =
      pay.note || "付款时请在备注/说明里填写订单号，付完回到本页点「我已付款」。";
    $("cfgPushPlus").value = "";
    $("cfgPushPlus").placeholder = pay.pushPlusToken
      ? "已配置，留空则不修改"
      : "在 pushplus.plus 获取 token";
    if (!$("editDate").value) $("editDate").value = new Date().toISOString().slice(0, 10);
    renderList();
    refreshOrders().catch(() => {});
    $("saveHint").textContent =
      "保存后会写入服务器。浏览量会自动累计；密码/PushPlus 留空表示不改。付费条目请填「发货链接」。";
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
            <h4>${escapeHtml(p.title || "未命名")}${p.price ? ` <span class="price-tag">${escapeHtml(String(p.price).includes("元") ? p.price : p.price + "元")}</span>` : ""}${p.hidden ? ` <span class="pill">已下架</span>` : ""}</h4>
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
    data.site.name = $("cfgName").value.trim() || "小米素材站";
    data.site.subtitle = $("cfgSub").value.trim();
    data.site.footer = $("cfgFooter").value.trim();
    const newPwd = $("cfgPassword").value.trim();
    // Blank means keep server-side password (API redacts it from GET)
    data.site.adminPassword = newPwd;
    data.site.pay = data.site.pay || {};
    data.site.pay.wechatQr = $("cfgWechatQr").value.trim();
    data.site.pay.alipayQr = $("cfgAlipayQr").value.trim();
    data.site.pay.note = $("cfgPayNote").value.trim();
    const pp = $("cfgPushPlus").value.trim();
    data.site.pay.pushPlusToken = pp; // blank => server keeps old
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
    $("editPrice").value = p.price || "";
    $("editSubtitle").value = p.subtitle || "";
    $("editCover").value = p.cover || "";
    $("editSummary").value = p.summary || "";
    $("editDownloadNote").value = p.downloadNote || "";
    $("editLink").value = p.link || "";
    $("editFulfillment").value = p.fulfillmentLink || "";
    $("editGallery").value = (p.gallery || []).join("\n");
    $("editSeries").value = p.series || "";
    $("editTags").value = (p.tags || []).join(",");
    $("editDate").value = p.date || new Date().toISOString().slice(0, 10);
    $("editViews").value = Number(p.views || 0);
    $("editFlags").value = selectFromFlags(p);
    if ($("editHidden")) $("editHidden").checked = Boolean(p.hidden);
  }

  function resetForm() {
    $("editId").value = "";
    $("editTitle").value = "";
    $("editPrice").value = "";
    $("editSubtitle").value = "";
    $("editCover").value = "";
    $("editSummary").value = "";
    $("editDownloadNote").value = "";
    $("editLink").value = "";
    $("editFulfillment").value = "";
    $("editGallery").value = "";
    $("editSeries").value = "";
    $("editTags").value = "";
    $("editDate").value = new Date().toISOString().slice(0, 10);
    $("editViews").value = "0";
    $("editFlags").value = "none";
    if ($("editHidden")) $("editHidden").checked = false;
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
      price: $("editPrice").value.trim(),
      subtitle: $("editSubtitle").value.trim(),
      cover: $("editCover").value.trim(),
      summary: $("editSummary").value.trim(),
      downloadNote: $("editDownloadNote").value.trim(),
      link: $("editLink").value.trim(),
      fulfillmentLink: $("editFulfillment").value.trim(),
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
      hidden: Boolean($("editHidden")?.checked),
      updatedAt: new Date().toISOString(),
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
    const newPwd = $("cfgPassword").value.trim();
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
    if (newPwd) {
      password = newPwd;
      sessionStorage.setItem(AUTH_KEY, password);
      $("cfgPassword").value = "";
    }
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
    if (!password) {
      toast("请输入密码");
      return;
    }
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      toast(body.error || "密码错误");
      return;
    }
    await fetchContent();
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
  async function refreshOrders() {
    const box = $("ordersList");
    if (!box) return;
    const res = await fetch(`/api/orders?ts=${Date.now()}`, {
      headers: { "X-Admin-Password": password },
      cache: "no-store",
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || "加载订单失败");
    const orders = body.orders || [];
    box.innerHTML = orders.length
      ? orders
          .map((o) => {
            const pending = o.status === "pending" || o.status === "claimed";
            return `<div class="orders-row" data-oid="${escapeAttr(o.id)}">
              <div><b>${escapeHtml(o.id)}</b> · ${escapeHtml(o.amountLabel || "")} · ${escapeHtml(o.status || "")}</div>
              <div>${escapeHtml(o.title || "")}</div>
              <div class="muted">${escapeHtml(o.createdAt || "")}${o.claimedAt ? " · 已声明付款" : ""}</div>
              ${
                pending
                  ? `<div class="admin-actions">
                      <button class="btn btn-primary" data-oact="confirm">确认放行</button>
                      <button class="btn" data-oact="reject">驳回</button>
                    </div>`
                  : ""
              }
            </div>`;
          })
          .join("")
      : '<p class="muted">暂无订单。</p>';
  }

  async function orderAct(id, kind) {
    const res = await fetch(`/api/orders/${kind}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Password": password,
      },
      body: JSON.stringify({ id }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || "操作失败");
    toast(kind === "confirm" ? "已放行" : "已驳回");
    await refreshOrders();
  }

  $("exportBtn").addEventListener("click", exportJson);
  $("refreshOrdersBtn")?.addEventListener("click", () => {
    refreshOrders()
      .then(() => toast("订单已刷新"))
      .catch((e) => toast(e.message));
  });
  $("ordersList")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-oact]");
    const row = e.target.closest("[data-oid]");
    if (!btn || !row) return;
    orderAct(row.dataset.oid, btn.dataset.oact).catch((err) => toast(err.message));
  });
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
    fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    })
      .then((res) => {
        if (!res.ok) {
          sessionStorage.removeItem(AUTH_KEY);
          return null;
        }
        return fetchContent().then(() => showEditor());
      })
      .catch(() => {});
  }
})();
