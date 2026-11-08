(() => {
  const search = document.querySelector("#radar-search");
  const rows = [...document.querySelectorAll("[data-radar-row]")];
  const empty = document.querySelector("#radar-search-empty");
  search?.addEventListener("input", () => {
    const query = search.value.toLowerCase().trim();
    let visible = 0;
    rows.forEach((row) => {
      const shown = !query || row.dataset.search.toLowerCase().includes(query);
      row.hidden = !shown;
      if (shown) visible += 1;
    });
    if (empty) empty.hidden = visible > 0 || !query;
  });

  const svg = document.querySelector("#radar-chart");
  const copy = document.querySelector("#radar-copy");
  const download = document.querySelector("#radar-png-download");
  const status = document.querySelector("#radar-image-status");
  if (!svg || !copy || !download || !status) return;

  let blob;
  const filename = `${svg.dataset.filename || "radar"}.png`.replace(/[\\/:*?"<>|]+/g, "_");
  const serialize = () => {
    const source = new XMLSerializer().serializeToString(svg);
    return new Blob([`<?xml version="1.0" encoding="UTF-8"?>${source}`], {
      type: "image/svg+xml;charset=utf-8",
    });
  };
  const createPng = async () => {
    const image = new Image();
    image.decoding = "async";
    const svgBlob = serialize();
    const url = URL.createObjectURL(svgBlob);
    try {
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = reject;
        image.src = url;
      });
      const viewBox = svg.viewBox.baseVal;
      const scale = Math.max(2, Math.min(3, window.devicePixelRatio || 1));
      const canvas = document.createElement("canvas");
      canvas.width = Math.ceil(viewBox.width * scale);
      canvas.height = Math.ceil(viewBox.height * scale);
      const context = canvas.getContext("2d");
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
      if (!blob) throw new Error("PNG 图片生成失败。");
      copy.disabled = false;
      download.disabled = false;
      status.textContent = "图片已准备好，可复制到剪贴板或下载。";
    } finally {
      URL.revokeObjectURL(url);
    }
  };

  download.addEventListener("click", () => {
    if (!blob) return;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 0);
  });
  copy.addEventListener("click", async () => {
    try {
      if (!window.isSecureContext || !navigator.clipboard?.write || !window.ClipboardItem) {
        throw new Error("当前浏览器无法复制图片，请下载 PNG 后发送。");
      }
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      status.textContent = "已复制图片，可直接粘贴到微信。";
    } catch (error) {
      status.textContent = error.message?.startsWith("当前浏览器")
        ? error.message
        : "未能复制图片，请允许剪贴板访问，或下载 PNG 后发送。";
    }
  });
  createPng().catch(() => {
    status.textContent = "图片准备失败，请下载 SVG 后发送。";
  });
})();
