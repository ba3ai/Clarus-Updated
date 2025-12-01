// src/components/tabs/AddUser.jsx
import React, { useState } from "react";
import api from "../../services/api"; // Axios instance with CSRF + cookies

export default function AddUser({ onSuccess }) {
  const [form, setForm] = useState({
    name: "",
    email: "",
  });
  const [status, setStatus] = useState({ type: "", msg: "" });
  const [submitting, setSubmitting] = useState(false);

  const onChange = (e) =>
    setForm((f) => ({ ...f, [e.target.name]: e.target.value }));

  const resetForm = () => setForm({ name: "", email: "" });

  const submit = async (e) => {
    e.preventDefault();
    setStatus({ type: "", msg: "" });

    const name = form.name.trim();
    const email = form.email.trim().toLowerCase();

    if (!name || !email) {
      setStatus({
        type: "error",
        msg: "Name and email are required.",
      });
      return;
    }

    try {
      setSubmitting(true);

      // CSRF / cookie-based call — no JWT, no Authorization header.
      const { data } = await api.post("/api/admin/invite-admin", {
        name,
        email,
      });

      if (!data?.ok) {
        throw new Error(data?.error || data?.msg || "Invite failed.");
      }

      const msg =
        data?.mail_error && !data?.emailed
          ? `Admin invitation created. Email not sent (${data.mail_error}). You can use this link: ${data.accept_url}`
          : data?.msg || "Admin invitation created successfully.";

      setStatus({
        type: "success",
        msg,
      });
      resetForm();
      onSuccess?.();
    } catch (err) {
      const msg =
        err?.response?.data?.error ||
        err?.response?.data?.msg ||
        err?.message ||
        "Failed to send invite.";
      setStatus({ type: "error", msg });
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
            <p className="mt-1 text-sm text-gray-600">
              Invite a new admin user by email.
            </p>
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
                  "rounded-xl px-4 py-3 text-sm border break-words",
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
