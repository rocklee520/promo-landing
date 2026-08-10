(() => {
  const {
    escapeHtml,
    escapeAttr,
    titleWithPriceHtml,
    formatPrice,
    thumbUrl,
    loadContent,
    trackView,
    bindSearchForm,
    renderSiteChrome,
  } = window.Promo;
  const params = new URLSearchParams(location.search);
  const id = params.get("id");
  const root = document.getElementById("noteArticle");
  const ORDER_KEY = id ? `order:${id}` : "";

  bindSearchForm(document.getElementById("searchForm"));

  let sitePay = {};
  let pollTimer = null;

  function readSavedOrder() {
    if (!ORDER_KEY) return null;
    try {
      return JSON.parse(localStorage.getItem(ORDER_KEY) || "null");
    } catch {
      return null;
    }
  }

  function saveOrder(order) {
    if (!ORDER_KEY || !order?.id || !order?.buyerToken) return;
    localStorage.setItem(
      ORDER_KEY,
      JSON.stringify({ id: order.id, buyerToken: order.buyerToken })
    );
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function fetchOrder(orderId, token) {
    const res = await fetch(
      `/api/orders?id=${encodeURIComponent(orderId)}&token=${encodeURIComponent(token)}&ts=${Date.now()}`,
      { cache: "no-store" }
    );
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || "查询订单失败");
    return body.order;
  }

  function renderUnlocked(link) {
    const box = document.getElementById("payUnlock");
    if (!box) return;
    box.innerHTML = `
      <p class="pay-unlocked-title">付款已确认，下载链接如下</p>
      <p class="note-download-link"><a href="${escapeAttr(link)}" target="_blank" rel="noopener noreferrer">打开百度云 / 资源链接</a></p>
      <p class="muted pay-link-raw">${escapeHtml(link)}</p>
      <button type="button" class="btn" id="copyLinkBtn">复制链接</button>
    `;
    document.getElementById("copyLinkBtn")?.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(link);
        alert("已复制");
      } catch {
        prompt("复制链接：", link);
      }
    });
  }

  function renderWaiting(order) {
    const status = document.getElementById("payStatus");
    if (status) {
      status.innerHTML =
        order.status === "claimed"
          ? `<p>已通知站长确认，订单号 <b>${escapeHtml(order.id)}</b>。确认到账后这里会自动显示下载链接，请勿关闭页面。</p>`
          : `<p>订单已创建：<b>${escapeHtml(order.id)}</b>。付款后点「我已付款」。</p>`;
    }
  }

  function startPoll(orderId, token) {
    stopPoll();
    const tick = async () => {
      try {
        const order = await fetchOrder(orderId, token);
        renderWaiting(order);
        if (order.status === "paid" && order.fulfillmentLink) {
          stopPoll();
          renderUnlocked(order.fulfillmentLink);
        } else if (order.status === "rejected") {
          stopPoll();
          const status = document.getElementById("payStatus");
          if (status) status.innerHTML = `<p class="pay-error">订单已驳回，请重新点击购买下单。</p>`;
          localStorage.removeItem(ORDER_KEY);
        }
      } catch {
        /* ignore transient errors */
      }
    };
    tick();
    pollTimer = setInterval(tick, 4000);
  }

  function payPanelHtml(p) {
    const price = formatPrice(p.price);
    return `
      <div class="pay-panel" id="payPanel">
        <h1 class="note-h1">购买获取下载</h1>
        <p class="note-p">价格 <span class="price-tag">${escapeHtml(price)}</span>。扫码付款后，站长微信确认到账即可自动显示百度云链接。</p>
        <div class="admin-actions" style="margin:12px 0;">
          <button type="button" class="btn btn-primary" id="buyBtn">购买 / 查看收款码</button>
        </div>
        <div id="payBox" class="pay-box" hidden></div>
        <div id="payStatus" class="pay-status"></div>
        <div id="payUnlock"></div>
      </div>
    `;
  }

  function showPayBox(order, pay) {
    const box = document.getElementById("payBox");
    if (!box) return;
    const note = pay?.note || sitePay.note || "";
    const wechat = pay?.wechatQr || sitePay.wechatQr || "";
    const alipay = pay?.alipayQr || sitePay.alipayQr || "";
    box.hidden = false;
    box.innerHTML = `
      <div class="pay-order-row">
        <div>订单号（付款备注请填这个）</div>
        <div class="pay-order-id" id="payOrderId">${escapeHtml(order.id)}</div>
        <button type="button" class="btn" id="copyOrderBtn">复制订单号</button>
      </div>
      <p class="pay-amount">应付：<b>${escapeHtml(order.amountLabel || "")}</b></p>
      <p class="muted">${escapeHtml(note)}</p>
      <div class="pay-qr-grid">
        ${
          wechat
            ? `<figure><img src="${escapeAttr(wechat)}" alt="微信收款码" /><figcaption>微信</figcaption></figure>`
            : "<p class=\"muted\">尚未配置微信收款码</p>"
        }
        ${
          alipay
            ? `<figure><img src="${escapeAttr(alipay)}" alt="支付宝收款码" /><figcaption>支付宝</figcaption></figure>`
            : "<p class=\"muted\">尚未配置支付宝收款码</p>"
        }
      </div>
      <div class="admin-actions" style="margin-top:14px;">
        <button type="button" class="btn btn-primary" id="claimBtn">我已付款</button>
      </div>
    `;
    document.getElementById("copyOrderBtn")?.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(order.id);
        alert("订单号已复制，请粘贴到付款备注");
      } catch {
        prompt("订单号：", order.id);
      }
    });
    document.getElementById("claimBtn")?.addEventListener("click", () => {
      claimPaid(order).catch((e) => alert(e.message));
    });
  }

  async function createOrder(postId) {
    const res = await fetch("/api/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ postId }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || "下单失败");
    saveOrder(body.order);
    sitePay = body.pay || sitePay;
    showPayBox(body.order, body.pay || {});
    renderWaiting(body.order);
    startPoll(body.order.id, body.order.buyerToken);
    return body.order;
  }

  async function claimPaid(order) {
    const res = await fetch("/api/orders/claim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: order.id, token: order.buyerToken }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || "提交失败");
    renderWaiting(body.order || order);
    if (!body.pushed) {
      alert(
        "已记录「我已付款」，但微信推送失败：" +
          (body.pushMessage || "未配置 PushPlus") +
          "。请联系站长，或站长可在后台订单列表确认。"
      );
    } else {
      alert("已通知站长，确认到账后本页会自动显示下载链接。");
    }
    startPoll(order.id, order.buyerToken);
  }

  function bindPay(p) {
    document.getElementById("buyBtn")?.addEventListener("click", () => {
      createOrder(p.id).catch((e) => alert(e.message));
    });
    const saved = readSavedOrder();
    if (!saved) return;
    fetchOrder(saved.id, saved.buyerToken)
      .then((order) => {
        order.buyerToken = saved.buyerToken;
        showPayBox(order, sitePay);
        if (order.status === "paid" && order.fulfillmentLink) {
          renderUnlocked(order.fulfillmentLink);
        } else {
          renderWaiting(order);
          startPoll(saved.id, saved.buyerToken);
        }
      })
      .catch(() => localStorage.removeItem(ORDER_KEY));
  }

  function renderPost(p) {
    document.title = p.title || "详情";
    const gallery = Array.isArray(p.gallery) ? p.gallery : [];
    const paid = Boolean(p.purchaseRequired);
    const linkBlock =
      !paid && p.link
        ? `<p class="note-download-link"><a href="${escapeAttr(p.link)}" target="_blank" rel="noopener noreferrer">打开下载 / 资源链接</a></p>`
        : "";
    const purchaseBlock = paid ? payPanelHtml(p) : "";

    root.innerHTML = `
      <div class="note-inline-title">${titleWithPriceHtml(p)}</div>
      ${p.subtitle ? `<h1 class="note-h1">${escapeHtml(p.subtitle)}</h1>` : ""}
      <h1 class="note-h1">内容简介</h1>
      <p class="note-p"><strong>${escapeHtml(p.summary || "").replace(/\n/g, "<br>")}</strong></p>
      ${p.downloadNote ? `<p class="note-p note-download-note">${escapeHtml(p.downloadNote)}</p>` : ""}
      ${p.updates ? `<p class="note-p">${escapeHtml(p.updates).replace(/\n/g, "<br>")}</p>` : ""}
      ${linkBlock}
      ${purchaseBlock}
      <div class="note-gallery" id="noteGallery">
        ${gallery
          .map(
            (src) =>
              `<p class="note-img-wrap"><img src="${escapeAttr(thumbUrl(src, 480))}" data-full="${escapeAttr(src)}" alt="" loading="lazy" decoding="async" /></p>`
          )
          .join("")}
      </div>
      <h1 class="note-h1">内容图集预览</h1>
      <div class="note-meta">
        <span>${escapeHtml(p.date || "")}</span>
        <span id="viewCount">${Number(p.views || 0)} 浏览</span>
        <span>${escapeHtml((p.tags || []).join(" · "))}</span>
      </div>
    `;
    document.getElementById("noteGallery")?.addEventListener("click", (e) => {
      const img = e.target.closest("img[data-full]");
      if (!img) return;
      const full = img.getAttribute("data-full");
      if (full && img.src.indexOf("/img?") !== -1) {
        img.src = full;
        img.removeAttribute("data-full");
      }
    });
    if (paid) bindPay(p);
  }

  loadContent()
    .then(async (data) => {
      sitePay = data.site?.pay || {};
      const post = (data.posts || []).find((p) => p.id === id);
      if (!post || post.hidden) {
        renderSiteChrome(data, { activeNav: "全部" });
        root.innerHTML = `<div class="empty">${post?.hidden ? "该内容已下架。" : "未找到内容。"} <a href="/">返回首页</a></div>`;
        return;
      }
      renderSiteChrome(data, { activeNav: post.series || "全部" });
      renderPost(post);
      const result = await trackView(post.id);
      if (result && typeof result.views === "number") {
        const el = document.getElementById("viewCount");
        if (el) el.textContent = `${result.views} 浏览`;
      }
    })
    .catch((err) => {
      root.innerHTML = `<div class="empty">加载失败：${escapeHtml(err.message)}</div>`;
    });
})();
