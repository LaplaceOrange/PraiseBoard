(() => {
  const form = document.querySelector("#score-entry-form");
  if (!form) return;
  const target = form.querySelector("[name=target]");
  const category = form.querySelector("[name=category]");
  const points = form.querySelector("[name=points]");
  const update = () => {
    form.querySelector("[data-target-group]").hidden = target.value !== "group";
    form.querySelector("[data-target-students]").hidden = target.value !== "students";
    form.querySelector("[data-homework-subject]").hidden = category.value !== "homework";
    form.querySelector("[name=group]").required = target.value === "group";
    form.querySelector("[name=subject_id]").required = category.value === "homework";
    points.disabled = category.value === "note";
    if (category.value === "homework") {
      points.max = "0";
      if (Number(points.value) > 0) points.value = "-1";
    } else points.removeAttribute("max");
  };
  target.addEventListener("change", update);
  category.addEventListener("change", update);
  update();
  form.querySelector("#student-search").addEventListener("input", event => {
    const query = event.target.value.trim().toLowerCase();
    form.querySelectorAll("[data-student-search]").forEach(label => {
      label.hidden = !label.dataset.studentSearch.toLowerCase().includes(query);
    });
  });
})();
