// src/pages/ForgotPassword.jsx
import { useState } from "react";

/* ---------------- XSRF helpers (cookie-based auth) ---------------- */

function getCookie(name) {
  return (
    document.cookie
      .split("; ")
      .find((row) => row.startsWith(name + "="))
      ?.split("=")[1] || ""
  );
}

async function xsrfFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  // Attach XSRF header for non-GET (these are POSTs)
  if ((options.method && options.method !== "GET") || options.forceXsrf) {
    const token = getCookie("XSRF-TOKEN");
    if (token) headers.set("X-XSRF-TOKEN", token);
  }

  return fetch(url, {
    ...options,
    headers,
    credentials: "include", // important for cookie-based auth
  });
}

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function call(path) {
    setBusy(true);
    setMsg("");
    try {
      const res = await xsrfFetch(`/api/auth/password/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok && data?.error) throw new Error(data.error);
      setSent(true);
      if (data?.sent === false) {
        setMsg("We couldn't send the email right now. Try again in a moment.");
      } else {
        setMsg("If that email exists, we’ve sent a reset link.");
      }
    } catch (e) {
      setMsg(e.message || "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  const submit = (e) => {
    e.preventDefault();
    if (!email) return;
    call("forgot");
  };

  const resend = () => call("resend");

  return (
    <div className="min-h-screen grid place-items-center bg-emerald-500/10 p-6">
      <div className="w-full max-w-xl rounded-2xl bg-white p-8 shadow">
        <h1 className="text-2xl font-semibold mb-2">Forgot password</h1>

        {!sent ? (
          <form onSubmit={submit} className="space-y-4">
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-xl border px-4 py-2"
              placeholder="you@example.com"
            />
            <button
              disabled={busy}
              className="w-full rounded-xl bg-emerald-600 text-white py-2"
            >
              {busy ? "Sending..." : "Send reset link"}
            </button>
          </form>
        ) : (
          <div className="space-y-4">
            <p className="text-sm">
              {msg || "If that email exists, we’ve sent a reset link."}
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={resend}
                disabled={busy}
                className="rounded-lg border px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-60"
              >
                {busy ? "Resending..." : "Didn’t get it? Resend"}
              </button>
              <button
                onClick={() => setSent(false)}
                className="text-sm text-emerald-700 hover:underline"
              >
                Use a different email
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
