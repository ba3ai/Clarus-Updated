// src/pages/ResetPassword.jsx
import { useEffect, useMemo, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";

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
  if ((options.method && options.method !== "GET") || options.forceXsrf) {
    const token = getCookie("XSRF-TOKEN");
    if (token) headers.set("X-XSRF-TOKEN", token);
  }

  return fetch(url, {
    ...options,
    headers,
    credentials: "include",
  });
}

export default function ResetPassword() {
  const [sp] = useSearchParams();
  const token = useMemo(() => sp.get("token") || "", [sp]);

  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!token) setMsg("Invalid or missing reset link.");
  }, [token]);

  async function handleReset(e) {
    e.preventDefault();
    if (!token) return;

    if (pw.length < 8) {
      setMsg("Password must be at least 8 characters.");
      return;
    }
    if (pw !== confirm) {
      setMsg("Passwords do not match.");
      return;
    }

    try {
      setBusy(true);
      setMsg("");

      const res = await xsrfFetch("/api/auth/password/set", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password: pw, confirm }),
      });

      const data = await res.json().catch(() => ({}));

      if (res.ok && data.ok) {
        setDone(true);
        setMsg("Password reset complete. You can now log in.");
      } else {
        setMsg(data.error || "Unable to reset password.");
      }
    } catch (err) {
      setMsg("Network error. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (!token) return <div className="p-6 text-center">{msg}</div>;

  return (
    <div className="min-h-[60vh] flex items-center justify-center px-4">
      <div className="w-full max-w-md mx-auto p-8 bg-white rounded-2xl shadow">
        <h1 className="text-2xl font-semibold mb-4">Reset password</h1>

        {msg && <div className="mb-4 text-sm text-amber-700">{msg}</div>}

        {!done ? (
          <form onSubmit={handleReset} className="space-y-4">
            <input
              type="password"
              className="w-full rounded-xl border px-4 py-2"
              placeholder="New password"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              autoFocus
            />
            <input
              type="password"
              className="w-full rounded-xl border px-4 py-2"
              placeholder="Confirm password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
            <button
              className="w-full rounded-xl bg-emerald-600 text-white py-2 disabled:opacity-60"
              disabled={busy}
            >
              {busy ? "Updating…" : "Update password"}
            </button>
          </form>
        ) : (
          <div className="space-y-3">
            <p>Your password has been updated.</p>
            <Link to="/login" className="text-emerald-700 underline">
              Return to login
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
