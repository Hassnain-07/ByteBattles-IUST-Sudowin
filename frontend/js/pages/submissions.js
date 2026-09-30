// My submissions: GET /submissions/?problem_id=&page=&limit=
// (when logged in and no username is given, the API returns your own)

renderNav("submissions");

const LIMIT = 20;
let page = 1;

async function loadSubmissions() {
  const rows = $("#rows");
  rows.replaceChildren(el("tr", {}, el("td", { colspan: 6 }, loading())));
  clearMessage($("#message"));

  const problemId = $("#problem-filter").value.trim();
  const query = new URLSearchParams({ page, limit: LIMIT });
  if (problemId) query.set("problem_id", problemId);

  try {
    const subs = await api(`/submissions/?${query}`);

    rows.replaceChildren(
      ...(subs.length === 0
        ? [el("tr", {}, el("td", { colspan: 6, class: "muted" }, "No submissions yet. ", el("a", { href: "index.html" }, "Solve a problem!")))]
        : subs.map((s) =>
            el("tr", {},
              el("td", {}, el("a", { href: `submission.html?id=${s.id}` }, `#${s.id}`)),
              el("td", {}, formatDate(s.submitted_at)),
              el("td", {}, el("a", { href: `problem.html?id=${encodeURIComponent(s.problem_id)}` }, s.problem_id)),
              el("td", {}, verdictEl(s.verdict)),
              el("td", {}, formatMs(s.walltime_ms)),
              el("td", {}, formatKb(s.memory_kb))
            )
          ))
    );

    $("#page-label").textContent = `Page ${page}`;
    $("#prev").disabled = page <= 1;
    $("#next").disabled = subs.length < LIMIT;
  } catch (e) {
    rows.replaceChildren();
    showMessage($("#message"), e.message);
  }
}

$("#prev").addEventListener("click", () => { page -= 1; loadSubmissions(); });
$("#next").addEventListener("click", () => { page += 1; loadSubmissions(); });
$("#filter").addEventListener("click", () => { page = 1; loadSubmissions(); });
$("#refresh").addEventListener("click", loadSubmissions);
$("#problem-filter").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { page = 1; loadSubmissions(); }
});

$("#problem-filter").value = getParam("problem") || "";
if (requireLogin()) loadSubmissions();
