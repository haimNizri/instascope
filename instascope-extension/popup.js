const API_BASE = "https://igai.app";
let igUser = "";

// ── Status helpers ─────────────────────────────────────────────────────────

function setStatus(msg, type = "info") {
  const box = document.getElementById("statusBox");
  box.textContent = msg;
  box.className = "status " + type;
}

function openUrl(path) {
  chrome.tabs.create({ url: API_BASE + path });
}

// ── Check if logged into InstaScope ────────────────────────────────────────

async function checkSession() {
  try {
    const resp = await fetch(API_BASE + "/api/session", { credentials: "include" });
    const data = await resp.json();

    if (data.logged_in) {
      igUser = data.username;
      showMainView(data.username);
    } else {
      // Check if we have saved credentials
      const saved = await chrome.storage.local.get(["email", "token"]);
      if (saved.token) {
        showMainView(null, true);
        setStatus("Instagram session expired. Click Connect.", "warning");
      } else {
        showLoginForm();
      }
    }
  } catch (e) {
    // Try with saved token
    const saved = await chrome.storage.local.get(["email", "token"]);
    if (saved.token) {
      showMainView(null, true);
    } else {
      showLoginForm();
    }
  }
}

// ── Login ──────────────────────────────────────────────────────────────────

function showLoginForm() {
  document.getElementById("loginForm").style.display = "block";
  document.getElementById("mainView").style.display = "none";
  setStatus("Sign in to InstaScope to get started", "info");
}

async function doLogin() {
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;
  if (!email || !password) {
    setStatus("Enter email and password", "error");
    return;
  }

  const btn = document.getElementById("loginBtn");
  btn.disabled = true;
  btn.textContent = "Signing in...";

  try {
    // Login via form POST
    const formData = new URLSearchParams();
    formData.append("email", email);
    formData.append("password", password);

    const resp = await fetch(API_BASE + "/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: formData.toString(),
      credentials: "include",
      redirect: "follow",
    });

    // Check if login succeeded by hitting the session endpoint
    const sessionResp = await fetch(API_BASE + "/api/session", { credentials: "include" });
    const sessionData = await sessionResp.json();

    if (sessionData.logged_in) {
      igUser = sessionData.username;
      // Save email for convenience
      await chrome.storage.local.set({ email, token: "logged_in" });
      showMainView(sessionData.username);
    } else {
      setStatus("Invalid email or password", "error");
      btn.disabled = false;
      btn.textContent = "Sign In";
    }
  } catch (e) {
    setStatus("Connection error: " + e.message, "error");
    btn.disabled = false;
    btn.textContent = "Sign In";
  }
}

// ── Main view ──────────────────────────────────────────────────────────────

function showMainView(username, sessionExpired = false) {
  document.getElementById("loginForm").style.display = "none";
  document.getElementById("mainView").style.display = "block";

  if (username) {
    igUser = username;
    document.getElementById("connectedInfo").innerHTML =
      `Connected as <span class="username">@${username}</span>`;
    setStatus("Instagram connected! Ready to scan.", "success");
  } else if (sessionExpired) {
    setStatus("Click Connect to link your Instagram", "warning");
  }
}

// ── Connect Instagram (the magic part) ─────────────────────────────────────

async function connectInstagram() {
  const btn = document.getElementById("connectBtn");
  btn.disabled = true;
  btn.textContent = "Connecting...";
  setStatus("Reading Instagram cookies...", "info");

  try {
    // Use Chrome extension API to read Instagram cookies
    const cookie = await chrome.cookies.get({
      url: "https://www.instagram.com",
      name: "sessionid",
    });

    if (!cookie || !cookie.value) {
      setStatus("Not logged into Instagram. Go to instagram.com and log in first.", "error");
      btn.disabled = false;
      btn.textContent = "Connect Instagram";
      return;
    }

    setStatus("Sending session to InstaScope...", "info");

    // Send to our server
    const resp = await fetch(API_BASE + "/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ session_id: cookie.value }),
    });

    const data = await resp.json();

    if (data.ok) {
      igUser = data.username;
      document.getElementById("connectedInfo").innerHTML =
        `Connected as <span class="username">@${data.username}</span>`;
      setStatus("Connected! You can now use all features.", "success");
      btn.textContent = "Reconnect Instagram";
    } else if (resp.status === 403) {
      // Username mismatch
      setStatus(data.error || "Instagram account doesn't match your registration.", "error");
      btn.textContent = "Connect Instagram";
    } else {
      setStatus(data.error || "Failed to connect", "error");
      btn.textContent = "Connect Instagram";
    }
  } catch (e) {
    setStatus("Error: " + e.message, "error");
    btn.textContent = "Connect Instagram";
  }

  btn.disabled = false;
}

// ── Init ───────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", checkSession);
