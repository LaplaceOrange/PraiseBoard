(() => {
  const shell = document.querySelector(".pb-shell");
  if (!shell) return;
  const sidebar = shell.querySelector(".pb-sidebar");
  const main = shell.querySelector(".pb-main");
  const trigger = shell.querySelector("[data-toggle-nav]");
  const backdrop = shell.querySelector("[data-nav-backdrop]");
  const mobile = window.matchMedia("(max-width: 759px)");
  const setOpen = (open, restoreFocus = false) => {
    open = open && mobile.matches;
    shell.classList.toggle("is-nav-open", open);
    document.body.classList.toggle("pb-nav-open", open);
    trigger.setAttribute("aria-expanded", String(open));
    backdrop.hidden = !open;
    sidebar.inert = mobile.matches && !open;
    main.inert = open;
    if (open) {
      requestAnimationFrame(() => {
        if (shell.classList.contains("is-nav-open")) sidebar.querySelector("[data-close-nav]").focus();
      });
    }
    else if (restoreFocus) trigger.focus();
  };
  trigger.addEventListener("click", () => setOpen(true));
  sidebar.querySelector("[data-close-nav]").addEventListener("click", () => setOpen(false, true));
  backdrop.addEventListener("click", () => setOpen(false, true));
  document.addEventListener("keydown", (event) => {
    if (!shell.classList.contains("is-nav-open")) return;
    if (event.key === "Escape") setOpen(false, true);
    if (event.key !== "Tab") return;
    const controls = [...sidebar.querySelectorAll("a[href], button:not(:disabled)")];
    const first = controls[0];
    const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  mobile.addEventListener("change", () => setOpen(false));
  setOpen(false);
})();
document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
document.querySelector("[data-finalize]")?.addEventListener("click", (event) => {
  if (!window.confirm("定稿后将锁定当天内容。确认定稿？")) event.preventDefault();
});
document.querySelectorAll("[data-search-table]").forEach((search) => {
  search.addEventListener("input", () => {
    const query = search.value.toLowerCase().trim();
    let visible = 0;
    document.querySelectorAll(`#${search.dataset.searchTable} tbody tr`).forEach((row) => {
      row.hidden = !row.textContent.toLowerCase().includes(query);
      if (!row.hidden) visible++;
    });
    const empty = document.querySelector(`[data-search-empty="${search.dataset.searchTable}"]`);
    if (empty) empty.hidden = visible > 0 || !query;
  });
});
document.querySelectorAll("[data-toggle-password]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.togglePassword);
    const visible = input.type === "password";
    input.type = visible ? "text" : "password";
    const label = visible ? "隐藏密码" : "显示密码";
    button.setAttribute("aria-label", label);
    button.setAttribute("aria-pressed", String(visible));
    button.title = label;
    const icon = button.querySelector("img");
    icon.src = visible ? icon.dataset.visibleIcon : icon.dataset.hiddenIcon;
  });
});
const login = document.querySelector("#teacher-login");
if (login) {
  const classroom = login.querySelector("#classroom");
  const identity = login.querySelector("#identity");
  let pending;
  classroom.addEventListener("change", async () => {
    pending?.abort();
    const controller = new AbortController();
    pending = controller;
    identity.replaceChildren(new Option("选择科目与姓名", ""));
    identity.disabled = true;
    const feedback = document.querySelector("#login-feedback");
    feedback.textContent = "";
    if (!classroom.value) {
      return;
    }
    identity.options[0].text = "正在加载身份…";
    try {
      const response = await fetch(`${login.dataset.identitiesUrl}?classroom=${encodeURIComponent(classroom.value)}`, { signal: controller.signal });
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (pending !== controller) return;
      identity.options[0].text = "选择科目与姓名";
      data.identities.forEach((value) => identity.append(new Option(value.label, value.id)));
      if (!data.identities.length) feedback.textContent = "此班尚未分配任课老师，请联系管理员。";
    } catch (error) {
      if (pending === controller && error.name !== "AbortError") {
        identity.options[0].text = "身份加载失败";
        feedback.textContent = "身份列表加载失败，请重新选择班级。";
      }
    } finally {
      if (pending === controller) identity.disabled = identity.options.length < 2;
    }
  });
  identity.disabled = identity.options.length < 2;
  login.addEventListener("submit", (event) => {
    if (!identity.value || identity.disabled) {
      event.preventDefault();
      document.querySelector("#login-feedback").textContent = "请先选择班级和科目与姓名。";
      return;
    }
    const button = login.querySelector("button[type=submit]");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = "正在登录…";
  });
}
