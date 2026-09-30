// Problem list: GET /problems/?page=&limit=

renderNav("problems");

let page = Number(getParam("page")) || 1;

async function loadProblems() {
  const limit = Number($("#limit").value);
  const rows = $("#problem-rows");
  rows.replaceChildren(el("tr", {}, el("td", { colspan: 5 }, loading())));
  clearMessage($("#message"));

  try {
    const problems = await api(`/problems/?page=${page}&limit=${limit}`);

    if (problems.length === 0) {
      rows.replaceChildren(
        el("tr", {}, el("td", { colspan: 5, class: "muted" },
          page === 1 ? "No problems yet. An admin can add one from the Admin page." : "No more problems."))
      );
    } else {
      rows.replaceChildren(
        ...problems.map((p) =>
          el(
            "tr",
            {},
            el("td", {}, el("a", { href: `problem.html?id=${encodeURIComponent(p.id)}` }, p.id)),
            el("td", {}, el("a", { href: `problem.html?id=${encodeURIComponent(p.id)}` }, p.title)),
            el("td", {}, difficultyEl(p.difficulty)),
            el("td", {}, tagsEl(p.tags)),
            el("td", {}, `${p.accepted_submissions} accepted`)
          )
        )
      );
    }

    $("#page-label").textContent = `Page ${page}`;
    $("#prev").disabled = page <= 1;
    // The API doesn't return a total count, so a short page means it's the last one
    $("#next").disabled = problems.length < limit;
  } catch (e) {
    rows.replaceChildren();
    showMessage($("#message"), e.message);
  }
}

$("#prev").addEventListener("click", () => { page -= 1; loadProblems(); });
$("#next").addEventListener("click", () => { page += 1; loadProblems(); });
$("#limit").addEventListener("change", () => { page = 1; loadProblems(); });

loadProblems();
