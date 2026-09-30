// Problem page: show the statement, submit code, poll for the verdict.
//   GET  /problems/{id}
//   POST /submissions/
//   GET  /submissions/{id}          (polled until the verdict is no longer "PD")
//   GET  /submissions/?problem_id=  (your earlier attempts)

renderNav("problems");

const problemId = getParam("id");

const TEMPLATES = {
  PY: `a, b = map(int, input().split())\nprint(a + b)\n`,
  CPP: `#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    long long a, b;\n    cin >> a >> b;\n    cout << a + b << "\\n";\n    return 0;\n}\n`,
  C: `#include <stdio.h>\n\nint main(void) {\n    long long a, b;\n    scanf("%lld %lld", &a, &b);\n    printf("%lld\\n", a + b);\n    return 0;\n}\n`,
};

const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 120000;

// ---------------------------------------------------------------- statement

function section(title, ...content) {
  return [el("h3", {}, title), ...content];
}

function renderStatement(p) {
  document.title = `${p.title} - ByteBattles`;

  const sampleRows = Object.entries(p.sample_io).map(([input, output]) =>
    el("div", { class: "grid-2" },
      el("div", {}, el("div", { class: "small muted" }, "Input"), el("pre", {}, input)),
      el("div", {}, el("div", { class: "small muted" }, "Output"), el("pre", {}, output))
    )
  );

  $("#statement").replaceChildren(
    el("div", { class: "row" },
      el("h1", {}, `${p.id}. ${p.title}`),
      p.visibility ? null : el("span", { class: "badge" }, "Hidden (only admins see this)")
    ),
    el("div", { class: "row small" },
      difficultyEl(p.difficulty),
      tagsEl(p.tags),
      el("span", { class: "muted" }, `Time limit: ${p.time_limit_sec} s`),
      el("span", { class: "muted" }, `Memory limit: ${p.memory_limit_mb} MB`),
      el("span", { class: "muted" }, `${p.accepted_submissions} accepted`)
    ),
    ...section("Description", el("div", { class: "pre-wrap" }, p.description)),
    ...section("Input", el("div", { class: "pre-wrap" }, p.input_desc)),
    ...section("Output", el("div", { class: "pre-wrap" }, p.output_desc)),
    ...(p.constraints.length ? section("Constraints", el("ul", {}, p.constraints.map((c) => el("li", {}, c)))) : []),
    ...(sampleRows.length ? section("Examples", ...sampleRows) : []),
    ...(p.explanation ? section("Explanation", el("div", { class: "pre-wrap" }, p.explanation)) : []),
    ...(p.editorial ? [el("details", {}, el("summary", {}, "Editorial (spoilers)"), el("div", { class: "pre-wrap" }, p.editorial))] : []),
    p.source ? el("p", { class: "small muted" }, `Source: ${p.source}`) : null
  );
}

// ---------------------------------------------------------------- editor

function loadTemplate(language) {
  $("#code").value = TEMPLATES[language];
}

// Tab inserts four spaces instead of moving focus out of the editor
$("#code").addEventListener("keydown", (event) => {
  if (event.key !== "Tab") return;
  event.preventDefault();
  const area = event.target;
  const start = area.selectionStart;
  area.setRangeText("    ", start, area.selectionEnd, "end");
});

$("#language").addEventListener("change", () => {
  const code = $("#code").value.trim();
  const isTemplate = Object.values(TEMPLATES).some((t) => t.trim() === code);
  // swap templates freely, but never throw away code the user wrote
  if (!code || isTemplate) loadTemplate($("#language").value);
});

$("#reset-code").addEventListener("click", () => {
  if (confirm("Replace your code with the template?")) loadTemplate($("#language").value);
});

// ---------------------------------------------------------------- results

function renderResult(sub) {
  const children = [
    el("div", { class: "row" },
      sub.verdict === "PD" ? el("span", { class: "spinner" }) : null,
      verdictEl(sub.verdict),
      el("span", { class: "spacer" }),
      el("a", { href: `submission.html?id=${sub.id}`, class: "small" }, `Submission #${sub.id}`)
    ),
  ];

  if (sub.verdict === "PD") {
    children.push(el("p", { class: "muted small" }, "Waiting for the judge..."));
  } else {
    children.push(
      el("div", { class: "stats" },
        el("div", {}, el("span", {}, "Time"), formatMs(sub.walltime_ms)),
        el("div", {}, el("span", {}, "Memory"), formatKb(sub.memory_kb)),
        el("div", {}, el("span", {}, "Language"), LANGUAGES[sub.language] || sub.language)
      )
    );
    if (sub.verdict === "CE" && sub.output) {
      children.push(el("div", { class: "small muted" }, "Compiler output"), el("pre", {}, sub.output));
    }
    if (["WA", "TLE", "MLE", "RE"].includes(sub.verdict) && sub.incorrect_testcase) {
      children.push(el("div", { class: "small muted" }, "Failed on input"), el("pre", {}, sub.incorrect_testcase));
      if (sub.verdict === "WA") {
        children.push(el("div", { class: "small muted" }, "Your output"), el("pre", {}, sub.output || "(empty)"));
      }
    }
  }

  $("#result").replaceChildren(el("div", { class: "verdict-box" }, children));
}

async function pollSubmission(id) {
  const started = Date.now();
  while (Date.now() - started < POLL_TIMEOUT_MS) {
    const sub = await api(`/submissions/${id}`);
    renderResult(sub);
    if (sub.verdict !== "PD") return;
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
  $("#result").append(el("div", { class: "message info" },
    "Still pending after 2 minutes. The judge may be busy or not running - check back on the My Submissions page."));
}

$("#submit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!requireLogin()) return;

  const button = $("#submit");
  button.disabled = true;
  clearMessage($("#message"));

  try {
    const sub = await api("/submissions/", {
      method: "POST",
      json: { problem_id: problemId, language: $("#language").value, code: $("#code").value },
    });
    renderResult(sub);
    await pollSubmission(sub.id);
    loadHistory();
  } catch (e) {
    showMessage($("#result"), e.message);
  } finally {
    button.disabled = false;
  }
});

// ---------------------------------------------------------------- history

async function loadHistory() {
  if (!auth.isLoggedIn()) return;
  try {
    const subs = await api(`/submissions/?problem_id=${encodeURIComponent(problemId)}&limit=20`);
    $("#history-card").hidden = subs.length === 0;
    $("#history-rows").replaceChildren(
      ...subs.map((s) =>
        el("tr", {},
          el("td", {}, el("a", { href: `submission.html?id=${s.id}` }, `#${s.id}`)),
          el("td", {}, formatDate(s.submitted_at)),
          el("td", {}, verdictEl(s.verdict)),
          el("td", {}, formatMs(s.walltime_ms)),
          el("td", {}, formatKb(s.memory_kb))
        )
      )
    );
  } catch {
    $("#history-card").hidden = true;
  }
}

// ---------------------------------------------------------------- start

async function init() {
  if (!problemId) {
    $("#statement").replaceChildren(el("p", {}, "No problem selected. ", el("a", { href: "index.html" }, "Back to problems")));
    return;
  }

  try {
    const problem = await api(`/problems/${encodeURIComponent(problemId)}`);
    renderStatement(problem);
  } catch (e) {
    $("#statement").replaceChildren(
      el("h1", {}, "Problem not found"),
      el("p", { class: "muted" }, e.message),
      el("a", { href: "index.html" }, "Back to problems")
    );
    return;
  }

  $("#submit-card").hidden = false;
  loadTemplate($("#language").value);

  if (!auth.isLoggedIn()) {
    $("#login-hint").hidden = false;
    $("#login-link").href = `login.html?next=${encodeURIComponent(location.pathname + location.search)}`;
  }
  loadHistory();
}

init();
