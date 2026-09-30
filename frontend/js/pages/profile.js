// Profile page
//   GET   /users/{username}
//   GET   /users/{username}/solved_problems
//   GET   /users/{username}/submissions
//   PATCH /users/me   (account settings, own profile only)

renderNav();

const username = getParam("u") || auth.username;

async function loadProfile() {
  if (!username) {
    requireLogin();
    return;
  }

  const isMe = auth.isLoggedIn() && username === auth.username;

  let user;
  try {
    user = await api(`/users/${encodeURIComponent(username)}`);
  } catch (e) {
    $("#profile").replaceChildren(
      el("h1", {}, username),
      el("p", { class: "muted" },
        e.status === 404 ? "This user doesn't exist, or hasn't verified their account yet." : e.message)
    );
    return;
  }

  $("#profile").replaceChildren(
    el("h1", {}, user.username),
    el("div", { class: "stats" },
      user.email ? el("div", {}, el("span", {}, "Email"), user.email) : null,
      el("div", {}, el("span", {}, "Member since"), formatDate(user.created_at)),
      el("div", {}, el("span", {}, "Verified"), user.is_verified ? "Yes" : "No"),
      el("div", {}, el("span", {}, "Solved"), el("strong", { id: "solved-count" }, "..."))
    ),
    isMe && !user.is_verified
      ? el("p", { class: "muted small" }, "Your account isn't verified yet, so other people can't see your profile.")
      : null
  );

  $("#lists").hidden = false;
  $("#settings").hidden = !isMe;

  try {
    const [solved, recent] = await Promise.all([
      api(`/users/${encodeURIComponent(username)}/solved_problems`),
      api(`/users/${encodeURIComponent(username)}/submissions?limit=10`),
    ]);

    $("#solved-count").textContent = solved.length;
    $("#solved").replaceChildren(
      ...(solved.length
        ? solved.map((p) => el("li", {}, el("a", { href: `problem.html?id=${encodeURIComponent(p.id)}` }, `${p.id}. ${p.title}`)))
        : [el("li", { class: "muted" }, "Nothing solved yet.")])
    );

    $("#recent").replaceChildren(
      ...(recent.length
        ? recent.map((s) =>
            el("tr", {},
              el("td", {}, el("a", { href: `submission.html?id=${s.id}` }, `#${s.id}`)),
              el("td", {}, el("a", { href: `problem.html?id=${encodeURIComponent(s.problem_id)}` }, s.problem_id)),
              el("td", {}, verdictEl(s.verdict))
            ))
        : [el("tr", {}, el("td", { colspan: 3, class: "muted" }, "No submissions yet."))])
    );
  } catch (e) {
    $("#solved").replaceChildren(el("li", { class: "muted" }, e.message));
  }
}

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const box = $("#settings-message");
  clearMessage(box);

  const updates = {};
  const newUsername = $("#new-username").value.trim();
  const newEmail = $("#new-email").value.trim();
  const newPassword = $("#new-password").value;
  const confPassword = $("#new-conf-password").value;

  if (newUsername) updates.username = newUsername;
  if (newEmail) updates.email = newEmail;
  if (newPassword || confPassword) {
    if (newPassword !== confPassword) {
      showMessage(box, "Passwords don't match.");
      return;
    }
    updates.password = newPassword;
    updates.conf_password = confPassword;
  }
  if (Object.keys(updates).length === 0) {
    showMessage(box, "Nothing to change.", "info");
    return;
  }

  try {
    const me = await api("/users/me", { method: "PATCH", json: updates });
    auth.saveUsername(me.username);
    location.href = `profile.html?u=${encodeURIComponent(me.username)}&saved=1`;
  } catch (e) {
    showMessage(box, e.message);
  }
});

if (getParam("saved")) showMessage($("#settings-message"), "Saved.", "success");
loadProfile();
