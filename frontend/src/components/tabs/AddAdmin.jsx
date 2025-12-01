// src/components/tabs/AddAdmin.jsx
import React, { useState } from "react";

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
  // Attach XSRF header for non-GET (this is a POST)
  if ((options.method && options.method !== "GET") || options.forceXsrf) {
    const token = getCookie("XSRF-TOKEN");
    if (token) headers.set("X-XSRF-TOKEN", token);
  }

  return fetch(url, {
    ...options,
    headers,
    credentials: "include", // send session cookies
  });
}

const INVITE_API = "/api/admin/invite-admin";

export default function AddAdmin({ onSuccess }) {
  const [form, setForm] = useState({ name: "", email: "" });
  const [status, setStatus] = useState({ type: "", msg: "" });
  const [submitting, setSubmitting] = useState(false);

  const onChange = (e) =>
    setForm((f) => ({ ...f, [e.target.name]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setStatus({ type: "", msg: "" });

    try {
      setSubmitting(true);
      const res = await xsrfFetch(INVITE_API, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: form.name.trim(),
          email: form.email.trim(),
        }),
      });

      const data = await res.json().catch(() => ({}));

      if (res.status === 401 || res.status === 403) {
        setStatus({
          type: "error",
          msg: "You are not authorized. Please log in as an admin.",
        });
        return;
      }

      if (!res.ok || data.ok === false) {
        throw new Error(data?.error || `${res.status} ${res.statusText}`);
      }

      setStatus({
        type: "success",
        msg:
          data.emailed === false && data.accept_url
            ? "Admin invitation created. Email could not be sent, but you can copy the link: " +
              data.accept_url
            : "Admin invitation sent successfully!",
      });
      setForm({ name: "", email: "" });
      if (onSuccess) onSuccess();
    } catch (err) {
      setStatus({
        type: "error",
        msg: err.message || "Failed to send invite.",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-[60vh] w-full grid place-items-center px-4 py-8">
      <div className="relative w-full max-w-xl">
        <div className="absolute -inset-1 rounded-3xl bg-gradient-to-r from-indigo-500 via-fuchsia-500 to-rose-500 blur opacity-25 animate-pulse" />
        <div className="relative rounded-3xl border border-white/10 bg-white/60 backdrop-blur-xl shadow-2xl">
          <div className="p-6 sm:p-8 border-b border-black/5 bg-gradient-to-br from-white/80 to-white/40 rounded-t-3xl">
            <h1 className="text-xl sm:text-2xl font-semibold tracking-tight">
              Add Admin
            </h1>
          </div>

          <form onSubmit={submit} className="p-6 sm:p-8 space-y-5">
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-800">
                Name
              </label>
              <input
                name="name"
                value={form.name}
                onChange={onChange}
                required
                className="w-full rounded-xl border border-gray-200 bg-white/90 px-4 py-2.5 outline-none focus:ring-4 focus:ring-indigo-100 focus:border-indigo-400 transition"
              />
            </div>

            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-800">
                Email
              </label>
              <input
                type="email"
                name="email"
                value={form.email}
                onChange={onChange}
                required
                className="w-full rounded-xl border border-gray-200 bg-white/90 px-4 py-2.5 outline-none focus:ring-4 focus:ring-indigo-100 focus:border-indigo-400 transition"
              />
            </div>

            {status.msg && (
              <div
                className={[
                  "rounded-xl px-4 py-3 text-sm border",
                  status.type === "success"
                    ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                    : "bg-rose-50 border-rose-200 text-rose-700",
                ].join(" ")}
              >
                {status.msg}
              </div>
            )}

            <div className="pt-2">
              <button
                type="submit"
                disabled={submitting}
                className="inline-flex items-center justify-center rounded-xl bg-gradient-to-r from-indigo-600 to-fuchsia-600 text-white font-medium px-5 py-3 shadow-lg shadow-indigo-600/20 hover:shadow-fuchsia-600/25 hover:brightness-110 active:scale-[0.99] disabled:opacity-60 disabled:cursor-not-allowed transition-all duration-150"
              >
                {submitting ? "Sending…" : "Send Invitation"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
