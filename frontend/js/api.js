// Talks to the ByteBattles API.
// nginx forwards everything under /api/ to the FastAPI service, so the
// frontend and the API share one origin and no CORS setup is needed.

const API_BASE = "/api";

// ---------------------------------------------------------------- auth storage

const auth = {
  get accessToken() { return localStorage.getItem("access_token"); },
  get refreshToken() { return localStorage.getItem("refresh_token"); },
  get username() { return localStorage.getItem("username"); },

  isLoggedIn() {
    return Boolean(this.accessToken);
  },

  saveTokens(accessToken, refreshToken) {
    localStorage.setItem("access_token", accessToken);
    if (refreshToken) localStorage.setItem("refresh_token", refreshToken);
  },

  saveUsername(username) {
    localStorage.setItem("username", username);
  },

  clear() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    localStorage.removeItem("username");
  },
};

// ---------------------------------------------------------------- errors

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// FastAPI returns {"detail": "text"} for HTTP errors and
// {"detail": [{loc, msg}, ...]} for validation (422) errors.
function describeError(status, body) {
  if (body && typeof body.detail === "string") return body.detail;
  if (body && Array.isArray(body.detail)) {
    return body.detail
      .map((d) => {
        const field = (d.loc || []).filter((p) => p !== "body").join(".");
        const msg = (d.msg || "").replace(/^Value error, /, "");
        return field ? `${field}: ${msg}` : msg;
      })
      .join("\n");
  }
  if (status === 404) return "Not found.";
  if (status >= 500) return "Server error. Check the API logs (docker compose logs api).";
  return `Request failed (HTTP ${status}).`;
}

// ---------------------------------------------------------------- requests

async function tryRefreshToken() {
  if (!auth.refreshToken) return false;
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: auth.refreshToken }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  auth.saveTokens(data.access_token);
  return true;
}

/**
 * Call the API.
 *   api("/problems/")                                   GET
 *   api("/problems/tag", { method: "POST", json: {...} })  JSON body
 *   api("/auth/login", { method: "POST", form: {...} })    urlencoded form
 *   api("/problems/", { method: "POST", formData })        multipart (file upload)
 * Returns parsed JSON (or null for 204). Throws ApiError on failure.
 */
async function api(path, options = {}, isRetry = false) {
  const { method = "GET", json, form, formData } = options;
  const headers = {};
  let body;

  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form !== undefined) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    body = new URLSearchParams(form).toString();
  } else if (formData !== undefined) {
    body = formData; // browser sets the multipart boundary itself
  }

  if (auth.accessToken) headers["Authorization"] = `Bearer ${auth.accessToken}`;

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { method, headers, body });
  } catch (e) {
    throw new ApiError(0, "Could not reach the server. Is the app running?");
  }

  // Access token expired: refresh once and retry
  if (res.status === 401 && auth.refreshToken && !isRetry) {
    if (await tryRefreshToken()) return api(path, options, true);
    auth.clear();
  }

  if (res.status === 204) return null;

  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }

  if (!res.ok) throw new ApiError(res.status, describeError(res.status, data));
  return data;
}
