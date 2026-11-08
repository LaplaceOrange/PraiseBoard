(() => {
  const form = document.querySelector("#report-prepare");
  if (!form) return;
  const status = document.querySelector("#report-status");
  const pages = document.querySelector("#report-pages");
  const kind = document.querySelector("#report-kind");
  const subject = document.querySelector("#report-subject");
  const update = () => { subject.closest(".pb-field").hidden = kind.value !== "homework"; };
  kind.addEventListener("change", update);
  update();
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    status.textContent = "正在生成图片…";
    pages.replaceChildren();
    document.querySelector("#report-download").hidden = true;
    try {
      const response = await fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin" });
      if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) {
        throw Error("图片生成失败，请刷新页面或稍后重试。");
      }
      const data = await response.json();
      if (!Array.isArray(data.pages)) throw Error(data.error || "图片生成失败。");
      // Fetch PNGs before enabling copy so the click only performs the clipboard write.
      const images = await Promise.all(data.pages.map(async page => {
        const image = await fetch(page.url, { credentials: "same-origin" });
        if (!image.ok || !image.headers.get("content-type")?.startsWith("image/png")) throw Error("图片读取失败。");
        return { ...page, blob: await image.blob() };
      }));
      const download = document.querySelector("#report-download");
      download.href = data.download;
      download.hidden = false;
      for (const image of images) {
        const figure = document.createElement("figure");
        const preview = document.createElement("img");
        preview.src = image.url;
        preview.alt = `报告第 ${image.number} 页`;
        preview.loading = "lazy";
        const caption = document.createElement("figcaption");
        const label = document.createElement("strong");
        label.textContent = `第 ${image.number} 页`;
        const copy = document.createElement("button");
        copy.type = "button";
        copy.className = "pb-button pb-button--secondary";
        const icon = document.createElement("img");
        icon.src = "/static/icons/clipboard-list.svg";
        icon.alt = "";
        copy.append(icon, document.createTextNode("复制图片"));
        copy.addEventListener("click", async () => {
          try {
            if (!window.isSecureContext || !navigator.clipboard?.write || !window.ClipboardItem) {
              throw Error("当前浏览器无法复制图片，请下载图片后发送。");
            }
            await navigator.clipboard.write([new ClipboardItem({ "image/png": image.blob })]);
            status.textContent = `已复制第 ${image.number} 页图片。`;
          } catch (failure) {
            status.textContent = failure.message?.startsWith("当前浏览器")
              ? failure.message : "未能复制图片，请允许剪贴板访问，或下载图片后发送。";
          }
        });
        const save = document.createElement("a");
        save.className = "pb-button pb-button--secondary";
        save.href = image.url;
        save.download = `report-${image.number}.png`;
        save.textContent = "下载此页";
        caption.append(label, copy, save);
        figure.append(caption, preview);
        pages.append(figure);
      }
      status.textContent = `已生成 ${images.length} 页图片。`;
    } catch (failure) {
      status.textContent = failure.message || "网络连接失败，请重试。";
    } finally {
      button.disabled = false;
    }
  });
})();
