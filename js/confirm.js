(() => {
  const params = new URLSearchParams(location.search);
  const id = params.get("id") || "";
  const token = params.get("token") || "";
  const root = document.getElementById("confirmCard");

  function escapeHtml(str) {
    return String(str ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function render(order, message) {
    const status = order?.status || "";
    const paid = status === "paid";
    const rejected = status === "rejected";
    root.innerHTML = `
      <h1>订单确认</h1>
      ${message ? `<p class="confirm-msg">${escapeHtml(message)}</p>` : ""}
      <p>订单号：<b>${escapeHtml(order?.id || id)}</b></p>
      <p>商品：${escapeHtml(order?.title || "")}</p>
      <p>金额：<b>${escapeHtml(order?.amountLabel || "")}</b></p>
      <p>状态：<b>${escapeHtml(status || "未知")}</b></p>
      <div class="confirm-actions">
        <button class="btn btn-primary" id="confirmBtn" ${paid || rejected ? "disabled" : ""}>确认放行（已到账）</button>
        <button class="btn" id="rejectBtn" ${paid || rejected ? "disabled" : ""}>驳回</button>
      </div>
      <p class="muted">对照微信/支付宝收款记录无误后再点确认。确认后客户页面会自动显示下载链接。</p>
    `;
    document.getElementById("confirmBtn")?.addEventListener("click", () => act("confirm"));
    document.getElementById("rejectBtn")?.addEventListener("click", () => {
      if (confirm("确定驳回该订单？")) act("reject");
    });
  }

  async function load() {
    if (!id || !token) {
      root.innerHTML = `<div class="empty">链接无效，缺少订单参数。</div>`;
      return;
    }
    const res = await fetch(
      `/api/orders?id=${encodeURIComponent(id)}&token=${encodeURIComponent(token)}&ts=${Date.now()}`,
      { cache: "no-store" }
    );
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      root.innerHTML = `<div class="empty">${escapeHtml(body.error || "加载失败")}</div>`;
      return;
    }
    render(body.order);
  }

  async function act(kind) {
    const res = await fetch(`/api/orders/${kind}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, token }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      alert(body.error || "操作失败");
      return;
    }
    render(body.order, kind === "confirm" ? "已放行，客户页面将显示下载链接。" : "已驳回。");
  }

  load().catch((e) => {
    root.innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`;
  });
})();
