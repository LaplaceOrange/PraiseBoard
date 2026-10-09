(() => {
  const form = document.querySelector("#praise-editor");
  if (!form) return;
  const students = JSON.parse(document.querySelector("#student-data").textContent);
  const initial = JSON.parse(document.querySelector("#initial-items").textContent);
  const container = document.querySelector("#praise-items");
  const template = document.querySelector("#item-template");
  const error = document.querySelector("#editor-error");
  const status = document.querySelector("#editor-save-state");
  let dirty = false;
  let saving = false;
  const markDirty = () => {
    dirty = true;
    status.textContent = "有未保存的修改";
    status.classList.add("is-dirty");
  };
  const renumber = () => {
    container.querySelectorAll("[data-item-number]").forEach((element, index) => {
      element.textContent = index + 1;
    });
  };
  const add = (data = { title: "", note: "", student_ids: [], all_students: false }) => {
    if (container.children.length >= 30) {
      error.textContent = "最多可添加 30 个表扬项目。";
      return;
    }
    const item = template.content.firstElementChild.cloneNode(true);
    item.querySelector("[name=title]").value = data.title;
    item.querySelector("[name=note]").value = data.note;
    const all = item.querySelector("[name=all_students]");
    all.checked = data.all_students;
    const list = item.querySelector(".pb-student-list");
    students.forEach((student) => {
      const label = document.createElement("label");
      label.className = "pb-student-option";
      label.dataset.search = `${student.student_no} ${student.name}`.toLowerCase();
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = "student";
      input.value = student.id;
      input.checked = data.student_ids.includes(student.id);
      const text = document.createElement("span");
      text.textContent = student.name;
      const number = document.createElement("small");
      number.textContent = student.student_no;
      text.append(number);
      label.append(input, text);
      list.append(label);
    });
    const count = () => {
      const total = all.checked ? students.length : item.querySelectorAll("[name=student]:checked").length;
      item.querySelector("[data-selected-count]").textContent = all.checked ? `全班 ${total} 人` : `已选 ${total} 人`;
      item.querySelectorAll("[name=student]").forEach((input) => { input.disabled = all.checked; });
    };
    item.addEventListener("change", (event) => {
      if (event.target.type !== "search") markDirty();
      count();
    });
    item.addEventListener("input", (event) => {
      if (event.target.type !== "search") markDirty();
    });
    item.querySelector("[data-clear-students]").addEventListener("click", () => {
      all.checked = false;
      item.querySelectorAll("[name=student]").forEach((input) => { input.checked = false; });
      count();
      markDirty();
    });
    item.querySelector(".pb-student-search").addEventListener("input", (event) => {
      const query = event.target.value.trim().toLowerCase();
      let visible = 0;
      list.querySelectorAll("label").forEach((label) => {
        label.hidden = !label.dataset.search.includes(query);
        if (!label.hidden) visible++;
      });
      item.querySelector(".pb-student-empty").hidden = visible > 0;
    });
    item.querySelector(".pb-delete-item").addEventListener("click", () => {
      if (container.children.length === 1) {
        error.textContent = "至少保留一个表扬项目。";
        return;
      }
      item.remove();
      markDirty();
      renumber();
    });
    count();
    if (!students.length) {
      const empty = item.querySelector(".pb-student-empty");
      empty.textContent = "班级名单为空，请先添加或导入学生。";
      empty.hidden = false;
      all.disabled = true;
    }
    container.append(item);
    renumber();
    return item;
  };
  (initial.length ? initial : [undefined]).forEach((data) => add(data));
  document.querySelector("#add-item").addEventListener("click", () => {
    const item = add();
    if (!item) return;
    markDirty();
    item.querySelector("[name=title]").focus();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving) return;
    error.textContent = "";
    const items = [...container.children].map((item) => ({
      title: item.querySelector("[name=title]").value.trim(),
      note: item.querySelector("[name=note]").value.trim(),
      all_students: item.querySelector("[name=all_students]").checked,
      student_ids: [...item.querySelectorAll("[name=student]:checked")].map((input) => Number(input.value)),
    }));
    if (items.some((item) => !item.all_students && !item.student_ids.length) || !students.length) {
      error.textContent = "请为每个项目选择学生，或选择全班同学。班级为空时请先维护名单。";
      error.scrollIntoView({ behavior: "instant", block: "center" });
      return;
    }
    saving = true;
    status.textContent = event.submitter?.value === "draft" ? "正在保存草稿…" : "正在提交填报…";
    status.classList.remove("is-dirty");
    form.setAttribute("aria-busy", "true");
    const controls = [...form.querySelectorAll("button")];
    controls.forEach((button) => { button.disabled = true; });
    try {
      const response = await fetch(form.dataset.saveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value },
        credentials: "same-origin",
        body: JSON.stringify({ version: Number(form.dataset.version), mode: event.submitter?.value || "submit", items }),
      });
      if (response.redirected) {
        dirty = false;
        window.location.assign(response.url);
        return;
      }
      if (!response.headers.get("content-type")?.includes("application/json")) {
        const failure = new Error();
        failure.userMessage = "保存失败，请重新登录后重试。";
        throw failure;
      }
      const data = await response.json();
      if (!response.ok) {
        const failure = new Error();
        failure.userMessage = typeof data.error === "string" ? data.error : "保存失败，请重新登录后重试。";
        throw failure;
      }
      dirty = false;
      window.location.assign(data.redirect);
    } catch (failure) {
      error.textContent = failure.userMessage || "网络连接失败，填写内容仍保留在本页。";
      saving = false;
      form.removeAttribute("aria-busy");
      status.textContent = "保存失败，内容仍保留";
      status.classList.add("is-dirty");
      controls.forEach((button) => { button.disabled = false; });
    }
  });
  window.addEventListener("beforeunload", (event) => {
    if (dirty && !saving) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
})();
