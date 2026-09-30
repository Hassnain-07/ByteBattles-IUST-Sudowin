// Login: POST /auth/login (form fields), then GET /users/me to learn the username

renderNav();

if (getParam("registered")) {
  showMessage($("#message"), "Account created. You can log in now.", "success");
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#submit");
  button.disabled = true;
  clearMessage($("#message"));

  try {
    // OAuth2 password flow expects form fields, not JSON
    const tokens = await api("/auth/login", {
      method: "POST",
      form: { username: $("#username").value.trim(), password: $("#password").value },
    });
    auth.saveTokens(tokens.access_token, tokens.refresh_token);

    // The user may have logged in with their email, so ask who they are
    const me = await api("/users/me");
    auth.saveUsername(me.username);

    const next = getParam("next");
    // only follow same-site relative paths
    location.href = next && next.startsWith("/") && !next.startsWith("//") ? next : "index.html";
  } catch (e) {
    auth.clear();
    showMessage($("#message"), e.message);
    button.disabled = false;
  }
});
