// Admin panel
//   GET    /problems/?limit=100            list (admins also get hidden problems)
//   GET    /problems/{id}                  details (for visibility + edit form)
//   POST   /problems/                      create (multipart form + zip)
//   PATCH  /problems/{id}                  edit / show / hide
//   POST   /problems/{id}/rejudge
//   DELETE /problems/{id}
//   POST   /problems/tag
//   PATCH  /users/{username}/role

renderNav("admin");

let editingId = null; // null = creating a new problem

// ================================================================ manage table

async function loadManageTable() {
  const rows = $("#manage-rows");
  rows.replaceChildren(el("tr", {}, el("td", { colspan: 5 }, loading())));

  try {
    const list = await api("/problems/?limit=100");
    // The list doesn't include visibility, so fetch each problem's details
    const problems = await Promise.all(list.map((p) => api(`/problems/${encodeURIComponent(p.id)}`)));

    if (problems.length === 0) {
      rows.replaceChildren(el("tr", {}, el("td", { colspan: 5, class: "muted" }, "No problems yet. Create a tag, then a problem.")));
      return;
    }

    rows.replaceChildren(...problems.map(problemRow));
  } catch (e) {
    rows.replaceChildren();
    showMessage($("#manage-message"), e.message);
  }
}

function problemRow(p) {
  const pid = encodeURIComponent(p.id);

  const toggle = el("button", { class: "secondary small", onclick: () => setVisibility(p, !p.visibility) },
    p.visibility ? "Hide" : "Show");
  const edit = el("button", { class: "secondary small", onclick: () => openEditForm(p.id) }, "Edit");
  const rejudge = el("button", { class: "secondary small", onclick: () => rejudgeProblem(p.id) }, "Rejudge");
  const del = el("button", { class: "danger small", onclick: () => deleteProblem(p.id) }, "Delete");

  return el("tr", {},
    el("td", {}, el("a", { href: `problem.html?id=${pid}` }, p.id)),
    el("td", {}, p.title),
    el("td", {}, p.visibility ? "Yes" : el("span", { class: "muted" }, "Hidden")),
    el("td", {}, `${p.accepted_submissions}`),
    el("td", {}, el("div", { class: "row" }, toggle, edit, rejudge, del))
  );
}

async function runAction(action, successText) {
  clearMessage($("#manage-message"));
  try {
    const result = await action();
    showMessage($("#manage-message"), typeof successText === "function" ? successText(result) : successText, "success");
    loadManageTable();
  } catch (e) {
    showMessage($("#manage-message"), e.message);
  }
}

function setVisibility(p, visible) {
  runAction(
    () => api(`/problems/${encodeURIComponent(p.id)}`, { method: "PATCH", json: { visibility: visible } }),
    `${p.id} is now ${visible ? "visible" : "hidden"}.`
  );
}

function rejudgeProblem(id) {
  if (!confirm(`Re-run every submission of ${id}? All their verdicts go back to Pending.`)) return;
  runAction(
    () => api(`/problems/${encodeURIComponent(id)}/rejudge`, { method: "POST" }),
    (r) => `Requeued ${r.requeued} submission(s) of ${id}.`
  );
}

function deleteProblem(id) {
  if (!confirm(`Delete ${id}, its testcases and ALL its submissions? This can't be undone.`)) return;
  runAction(() => api(`/problems/${encodeURIComponent(id)}`, { method: "DELETE" }), `Deleted ${id}.`);
}

// ================================================================ problem form

function addSampleRow(input = "", output = "") {
  const row = el("div", { class: "grid-2 sample-row", style: "margin-bottom:8px" },
    el("textarea", { class: "sample-input", placeholder: "Example input" }),
    el("div", {},
      el("textarea", { class: "sample-output", placeholder: "Expected output" }),
      el("button", { type: "button", class: "secondary small", onclick: () => row.remove() }, "Remove example")
    )
  );
  row.querySelector(".sample-input").value = input;
  row.querySelector(".sample-output").value = output;
  $("#samples").append(row);
}

function resetProblemForm() {
  $("#problem-form").reset();
  $("#samples").replaceChildren();
  addSampleRow();
  clearMessage($("#problem-message"));
}

function openCreateForm() {
  editingId = null;
  resetProblemForm();
  $("#problem-form-title").textContent = "New problem";
  $("#problem-submit").textContent = "Create problem";
  $("#p-id").disabled = false;
  $("#zip-field").hidden = false;
  $("#p-zip").required = true;
  $("#problem-card").hidden = false;
  $("#problem-card").scrollIntoView({ behavior: "smooth" });
}

async function openEditForm(id) {
  clearMessage($("#manage-message"));
  let p;
  try {
    p = await api(`/problems/${encodeURIComponent(id)}`);
  } catch (e) {
    showMessage($("#manage-message"), e.message);
    return;
  }

  editingId = id;
  resetProblemForm();
  $("#samples").replaceChildren();

  $("#problem-form-title").textContent = `Edit ${p.id}`;
  $("#problem-submit").textContent = "Save changes";
  $("#p-id").value = p.id;
  $("#p-id").disabled = true;
  $("#p-title").value = p.title;
  $("#p-difficulty").value = p.difficulty;
  $("#p-tags").value = p.tags.join(", ");
  $("#p-time").value = p.time_limit_sec;
  $("#p-memory").value = p.memory_limit_mb;
  $("#p-description").value = p.description;
  $("#p-input").value = p.input_desc;
  $("#p-output").value = p.output_desc;
  $("#p-constraints").value = p.constraints.join("\n");
  $("#p-explanation").value = p.explanation || "";
  $("#p-source").value = p.source || "";
  $("#p-editorial").value = p.editorial || "";
  $("#p-visibility").checked = p.visibility;
  Object.entries(p.sample_io).forEach(([i, o]) => addSampleRow(i, o));
  if (!Object.keys(p.sample_io).length) addSampleRow();

  // Testcases can't be replaced through the API, so hide the upload when editing
  $("#zip-field").hidden = true;
  $("#p-zip").required = false;

  $("#problem-card").hidden = false;
  $("#problem-card").scrollIntoView({ behavior: "smooth" });
}

function readProblemForm() {
  const sampleIo = {};
  document.querySelectorAll(".sample-row").forEach((row) => {
    const input = row.querySelector(".sample-input").value;
    const output = row.querySelector(".sample-output").value;
    if (input.trim() || output.trim()) sampleIo[input] = output;
  });

  const optional = (value) => (value.trim() ? value : null);

  return {
    title: $("#p-title").value.trim(),
    difficulty: $("#p-difficulty").value,
    tags: $("#p-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
    time_limit_sec: Number($("#p-time").value),
    memory_limit_mb: Number($("#p-memory").value),
    description: $("#p-description").value,
    input_desc: $("#p-input").value,
    output_desc: $("#p-output").value,
    constraints: $("#p-constraints").value.split("\n").map((c) => c.trim()).filter(Boolean),
    sample_io: sampleIo,
    explanation: optional($("#p-explanation").value),
    source: optional($("#p-source").value),
    editorial: optional($("#p-editorial").value),
    visibility: $("#p-visibility").checked,
  };
}

$("#problem-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#problem-submit");
  const box = $("#problem-message");
  clearMessage(box);

  const data = readProblemForm();
  if (data.tags.length === 0) {
    showMessage(box, "Add at least one tag.");
    return;
  }

  button.disabled = true;
  try {
    if (editingId) {
      await api(`/problems/${encodeURIComponent(editingId)}`, { method: "PATCH", json: data });
      showMessage($("#manage-message"), `Saved ${editingId}.`, "success");
    } else {
      // Creating uses a multipart form: list/dict fields are sent as JSON strings
      const form = new FormData();
      form.append("id", $("#p-id").value.trim());
      for (const [key, value] of Object.entries(data)) {
        if (value === null) continue;
        form.append(key, typeof value === "object" ? JSON.stringify(value) : String(value));
      }
      form.append("tests_zip", $("#p-zip").files[0]);

      const created = await api("/problems/", { method: "POST", formData: form });
      showMessage($("#manage-message"), `Created ${created.id} with ${created.testcases} testcase(s).`, "success");
    }
    $("#problem-card").hidden = true;
    loadManageTable();
  } catch (e) {
    showMessage(box, e.message);
  } finally {
    button.disabled = false;
  }
});

$("#new-problem").addEventListener("click", openCreateForm);
$("#add-sample").addEventListener("click", () => addSampleRow());
$("#problem-cancel").addEventListener("click", () => { $("#problem-card").hidden = true; });

// ================================================================ tags

// Suggest a slug from the name while the slug field is untouched
$("#tag-name").addEventListener("input", () => {
  const slug = $("#tag-slug");
  if (slug.dataset.touched) return;
  slug.value = $("#tag-name").value.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 50);
});
$("#tag-slug").addEventListener("input", () => { $("#tag-slug").dataset.touched = "1"; });

$("#tag-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const box = $("#tag-message");
  try {
    const tag = await api("/problems/tag", {
      method: "POST",
      json: { name: $("#tag-name").value.trim(), slug: $("#tag-slug").value.trim() },
    });
    showMessage(box, `Created tag "${tag.name}" (slug: ${tag.slug}).`, "success");
    $("#tag-form").reset();
    delete $("#tag-slug").dataset.touched;
  } catch (e) {
    showMessage(box, e.message);
  }
});

// ================================================================ roles

$("#role-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const box = $("#role-message");
  const username = $("#role-username").value.trim();
  try {
    const result = await api(`/users/${encodeURIComponent(username)}/role`, {
      method: "PATCH",
      json: { user_type: $("#role-type").value },
    });
    showMessage(box, `${result.username} is now ${result.user_type === "ADMIN" ? "an admin" : "a regular user"}.`, "success");
  } catch (e) {
    showMessage(box, e.message);
  }
});

// ================================================================ start

if (requireLogin()) {
  if (getParam("edit")) openEditForm(getParam("edit"));
  loadManageTable();
}
