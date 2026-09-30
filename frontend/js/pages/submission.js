// One submission: GET /submissions/{id}. Keeps refreshing while the verdict is pending.

renderNav("submissions");

const submissionId = getParam("id");

function render(s) {
  document.title = `Submission #${s.id} - ByteBattles`;

  const parts = [
    el("div", { class: "row" },
      el("h1", {}, `Submission #${s.id}`),
      el("span", { class: "spacer" }),
      s.verdict === "PD" ? el("span", { class: "spinner" }) : null,
      el("span", { style: "font-size:20px" }, verdictEl(s.verdict))
    ),
    el("div", { class: "stats" },
      el("div", {}, el("span", {}, "Problem"), el("a", { href: `problem.html?id=${encodeURIComponent(s.problem_id)}` }, s.problem_id)),
      el("div", {}, el("span", {}, "User"), el("a", { href: `profile.html?u=${encodeURIComponent(s.username)}` }, s.username)),
      el("div", {}, el("span", {}, "Language"), LANGUAGES[s.language] || s.language),
      el("div", {}, el("span", {}, "Submitted"), formatDate(s.submitted_at)),
      el("div", {}, el("span", {}, "Time"), formatMs(s.walltime_ms)),
      el("div", {}, el("span", {}, "Memory"), formatKb(s.memory_kb))
    ),
  ];

  if (s.verdict === "CE" && s.output) {
    parts.push(el("h3", {}, "Compiler output"), el("pre", {}, s.output));
  } else if (s.verdict === "SKP" && s.output) {
    parts.push(el("div", { class: "message info" }, s.output));
  } else if (s.verdict !== "AC" && s.verdict !== "PD") {
    if (s.incorrect_testcase) parts.push(el("h3", {}, "Failed on input"), el("pre", {}, s.incorrect_testcase));
    if (s.verdict === "WA") parts.push(el("h3", {}, "Your output"), el("pre", {}, s.output || "(empty)"));
  }

  parts.push(el("h3", {}, "Code"), el("pre", {}, s.code));

  $("#details").replaceChildren(...parts);
}

async function load() {
  if (!submissionId) {
    $("#details").replaceChildren(el("p", {}, "No submission selected."));
    return;
  }
  try {
    const s = await api(`/submissions/${encodeURIComponent(submissionId)}`);
    render(s);
    if (s.verdict === "PD") setTimeout(load, 1500);
  } catch (e) {
    $("#details").replaceChildren(el("h1", {}, "Submission not found"), el("p", { class: "muted" }, e.message));
  }
}

load();
