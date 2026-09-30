// Register: POST /auth/register

renderNav();

$("#register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#submit");
  clearMessage($("#message"));

  if ($("#password").value !== $("#conf_password").value) {
    showMessage($("#message"), "Passwords don't match.");
    return;
  }

  button.disabled = true;
  try {
    await api("/auth/register", {
      method: "POST",
      json: {
        username: $("#username").value.trim(),
        email: $("#email").value.trim(),
        password: $("#password").value,
        conf_password: $("#conf_password").value,
      },
    });
    location.href = "login.html?registered=1";
  } catch (e) {
    showMessage($("#message"), e.message);
    button.disabled = false;
  }
});
