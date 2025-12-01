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
  // Attach XSRF header for non-GET or when explicitly forced
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

export default function ResetPassword() {
  const [sp] = useSearchParams();
  const token = useMemo(() => sp.get("token") || "", [sp]);

  const [step, setStep] = useState("set"); // set -> verify -> done
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) setMsg("Invalid or missing reset link.");
  }, [token]);

  async function handleSet(e) {
    e.preventDefault();
    if (!token) return;
    if (pw !== confirm || pw.length < 8) {
      setMsg("Passwords must match and be at least 8 characters.");
      return;
    }
    try {
      setBusy(true);
      setMsg("");
      const res = await xsrfFetch("/api/auth/password/set", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password: pw }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        setStep("verify");
        setMsg(
          data.phone_mask
            ? `We sent a 6-digit code to ${data.phone_mask}.`
            : "We sent a 6-digit code to your phone."
        );
      } else {
        setMsg(data.error || "Unable to proceed.");
      }
    } catch (err) {
      setMsg("Network error. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function handleVerify(e) {
    e.preventDefault();
    if (!token) return;
    if (!/^\d{6}$/.test(code)) {
      setMsg("Please enter the 6-digit code.");
      return;
    }
    try {
      setBusy(true);
      setMsg("");
      const res = await xsrfFetch("/api/auth/password/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, code }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        setStep("done");
        setMsg("Password reset complete. You can now log in.");
      } else {
        setMsg(data.error || "Verification failed.");
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

        {step === "set" && (
          <form onSubmit={handleSet} className="space-y-4">
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
              {busy ? "Sending code…" : "Continue"}
            </button>
          </form>
        )}

        {step === "verify" && (
          <form onSubmit={handleVerify} className="space-y-4">
            <input
              inputMode="numeric"
              pattern="\d{6}"
              maxLength={6}
              className="w-full rounded-xl border px-4 py-2 tracking-widest text-center"
              placeholder="Enter 6-digit code"
              value={code}
              onChange={(e) =>
                setCode(e.target.value.replace(/\D/g, ""))
              }
              autoFocus
            />
            <button
              className="w-full rounded-xl bg-emerald-600 text-white py-2 disabled:opacity-60"
              disabled={busy}
            >
              {busy ? "Verifying…" : "Verify & Finish"}
            </button>
          </form>
        )}

        {step === "done" && (
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
