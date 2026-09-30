// Helpers shared by every page: navigation bar, DOM building, formatting.

const VERDICTS = {
  PD: "Pending",
  AC: "Accepted",
  WA: "Wrong Answer",
  TLE: "Time Limit Exceeded",
  MLE: "Memory Limit Exceeded",
  CE: "Compilation Error",
  RE: "Runtime Error",
  SKP: "Skipped",
};

const LANGUAGES = {
  C: "C",
  CPP: "C++",
  PY: "Python 3",
};

// ---------------------------------------------------------------- DOM helpers

/**
 * Build an element. Text is always set with textContent, so user content
 * (code, output, names) can never inject HTML.
 *   el("a", { href: "/x", class: "tag" }, "text", otherElement)
 */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

function $(selector) {
  return document.querySelector(selector);
}

function getParam(name) {
  return new URLSearchParams(location.search).get(name);
}

function showMessage(container, text, type = "error") {
  container.replaceChildren(el("div", { class: `message ${type} pre-wrap` }, text));
}

function clearMessage(container) {
  container.replaceChildren();
}

function loading(text = "Loading...") {
  return el("p", { class: "muted" }, el("span", { class: "spinner" }), text);
}

// ---------------------------------------------------------------- formatting

function verdictEl(code) {
  return el("span", { class: `verdict ${code}`, title: VERDICTS[code] || code }, VERDICTS[code] || code);
}

function difficultyEl(difficulty) {
  const label = difficulty.charAt(0) + difficulty.slice(1).toLowerCase();
  return el("span", { class: `badge ${difficulty}` }, label);
}

function tagsEl(tags) {
  return el("span", {}, tags.map((t) => el("span", { class: "tag" }, t)));
}

function formatDate(iso) {
  // API sends naive UTC timestamps
  const date = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  return date.toLocaleString();
}

function formatMs(ms) {
  return ms === null || ms === undefined ? "-" : `${ms} ms`;
}

function formatKb(kb) {
  if (kb === null || kb === undefined) return "-";
  return kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`;
}

// ---------------------------------------------------------------- navigation

function renderNav(active) {
  const header = $("#site-header");
  if (!header) return;

  const links = [
    ["problems", "index.html", "Problems"],
    ["submissions", "submissions.html", "My Submissions"],
    ["admin", "admin.html", "Admin"],
  ];

  const navLinks = el(
    "nav",
    { class: "nav-links" },
    links.map(([key, href, label]) => el("a", { href, class: key === active ? "active" : null }, label))
  );

  let userArea;
  if (auth.isLoggedIn()) {
    userArea = el(
      "div",
      { class: "nav-user" },
      el("a", { href: `profile.html?u=${encodeURIComponent(auth.username || "")}` }, auth.username || "Profile"),
      el("button", { class: "link-button", onclick: logout }, "Log out")
    );
  } else {
    userArea = el(
      "div",
      { class: "nav-user" },
      el("a", { href: "login.html" }, "Log in"),
      el("a", { href: "register.html" }, "Register")
    );
  }

  header.replaceChildren(
    el(
      "div",
      { class: "inner" },
      el("a", { href: "index.html", class: "logo" }, "Byte", el("span", {}, "Battles")),
      navLinks,
      userArea
    )
  );
}

function logout() {
  auth.clear();
  location.href = "index.html";
}

// Send logged-out users to the login page, then back here afterwards
function requireLogin() {
  if (!auth.isLoggedIn()) {
    location.href = `login.html?next=${encodeURIComponent(location.pathname + location.search)}`;
    return false;
  }
  return true;
}
