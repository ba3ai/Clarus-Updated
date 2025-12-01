// src/pages/AcceptAdminInvite.jsx
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

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

export default function AcceptAdminInvite() {
  const navigate = useNavigate();
  const { token } = useParams();

  const [loading, setLoading] = useState(true);
  const [invite, setInvite] = useState({ email: "", name: "" });
  const [err, setErr] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    password: "",
    confirm: "",
    phone: "",
    address: "",
    company: "",
    country: "",
    state: "",
    city: "",
    tax_id: "",
  });
  const [showPw, setShowPw] = useState(false);

  // ---- Fetch and validate invite ----
  useEffect(() => {
    let ignore = false;

    async function load() {
      setLoading(true);
      setErr("");
      try {
        const res = await xsrfFetch(`/api/admin/invitations/${token}`, {
          method: "GET",
        });
        const data = await res.json();
        if (!res.ok || data.ok === false) {
          throw new Error(data.error || "Invalid or expired invitation.");
        }

        if (!ignore) {
          setInvite({ email: data.email, name: data.name || "" });
          if (data.name) {
            const parts = data.name.trim().split(/\s+/);
            setForm((f) => ({
              ...f,
              first_name: parts[0] || "",
              last_name: parts.slice(1).join(" ") || "",
              company: data.name || "",
            }));
          }
        }
      } catch (e) {
        if (!ignore) setErr(e.message || "Unable to load invitation.");
      } finally {
        if (!ignore) setLoading(false);
      }
    }

    if (token) load();
    return () => {
      ignore = true;
    };
  }, [token]);

  function onChange(e) {
    const { name, value } = e.target;
    setForm((f) => ({ ...f, [name]: value }));
  }

  function validatePassword(pw) {
    if (pw.length < 8) return "Password must be at least 8 characters.";
    if (!/[A-Z]/.test(pw)) return "Password must include an uppercase letter.";
    if (!/[a-z]/.test(pw)) return "Password must include a lowercase letter.";
    if (!/[0-9]/.test(pw)) return "Password must include a number.";
    return "";
  }

  async function onSubmit(e) {
    e.preventDefault();
    setErr("");

    const required = ["first_name", "last_name", "password", "confirm"];
    for (const k of required) {
      if (!form[k]) {
        setErr("Please fill in all required fields.");
        return;
      }
    }
    const pwErr = validatePassword(form.password);
    if (pwErr) return setErr(pwErr);
    if (form.password !== form.confirm) {
      return setErr("Passwords do not match.");
    }

    setSubmitting(true);
    try {
      const res = await xsrfFetch(
        `/api/admin/invitations/${token}/accept`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            first_name: form.first_name.trim(),
            last_name: form.last_name.trim(),
            password: form.password,
            // NEW FIELDS:
            phone: form.phone.trim() || null,
            address: form.address.trim() || null,
            company: form.company.trim() || null,
            country: form.country.trim() || null,
            state: form.state.trim() || null,
            city: form.city.trim() || null,
            tax_id: form.tax_id.trim() || null,
          }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(data.error || "Unable to accept invitation.");
      }

      navigate("/login", {
        replace: true,
        state: { flash: "Account created. Please log in." },
      });
    } catch (e) {
      setErr(e.message || "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  // ---- UI ----
  if (loading) {
    return (
      <div className="p-6">
        <div className="mx-auto max-w-xl">
          <div className="animate-pulse h-24 rounded-2xl bg-gray-100" />
        </div>
      </div>
    );
  }

  if (err) {
    return (
      <div className="p-6">
        <div className="mx-auto max-w-xl rounded-2xl border border-red-200 bg-red-50 p-6">
          <p className="text-red-700 font-medium">{err}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mx-auto max-w-2xl">
        <div className="rounded-2xl bg-white shadow-sm ring-1 ring-black/5 p-6">
          <h1 className="text-2xl font-bold tracking-tight">
            Accept Admin Invitation
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            Create your admin account. You’ll be redirected to the login page
            after submitting.
          </p>

          <form onSubmit={onSubmit} className="mt-6 space-y-5">
            <div>
              <label className="block text-sm font-medium text-gray-800">
                Email
              </label>
              <input
                value={invite.email}
                disabled
                className="mt-1 w-full rounded-xl border border-gray-200 bg-gray-100 px-4 py-2.5 text-gray-700"
              />
              <p className="mt-1 text-xs text-gray-500">
                Email is locked to the invited address.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-800">
                  First name*
                </label>
                <input
                  name="first_name"
                  value={form.first_name}
                  onChange={onChange}
                  autoComplete="given-name"
                  className="mt-1 w-full rounded-xl border border-gray-200 px-4 py-2.5 focus:ring-4 focus:ring-indigo-100 focus:border-indigo-400"
                  placeholder="Jane"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-800">
                  Last name*
                </label>
                <input
                  name="last_name"
                  value={form.last_name}
                  onChange={onChange}
                  autoComplete="family-name"
                  className="mt-1 w-full rounded-xl border border-gray-200 px-4 py-2.5 focus:ring-4 focus:ring-indigo-100 focus:border-indigo-400"
                  placeholder="Doe"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-800">
                  Password*
                </label>
                <div className="relative">
                  <input
                    type={showPw ? "text" : "password"}
                    name="password"
                    value={form.password}
                    onChange={onChange}
                    autoComplete="new-password"
                    className="mt-1 w-full rounded-xl border border-gray-200 px-4 py-2.5 pr-12 focus:ring-4 focus:ring-indigo-100 focus:border-indigo-400"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-500"
                  >
                    {showPw ? "Hide" : "Show"}
                  </button>
                </div>
                <p className="mt-1 text-xs text-gray-500">
                  At least 8 chars incl. upper/lowercase and a number.
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-800">
                  Confirm password*
                </label>
                <input
                  type="password"
                  name="confirm"
                  value={form.confirm}
                  onChange={onChange}
                  autoComplete="new-password"
                  className="mt-1 w-full rounded-xl border border-gray-200 px-4 py-2.5 focus:ring-4 focus:ring-indigo-100 focus:border-indigo-400"
                />
              </div>
            </div>

            {/* New fields */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-800">
                  Phone
                </label>
                <input
                  name="phone"
                  value={form.phone}
                  onChange={onChange}
                  className="mt-1 w-full rounded-xl border border-gray-200 px-4 py-2.5"
                  placeholder="+1 555 123 4567"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-800">
                  Company
                </label>
                <input
                  name="company"
                  value={form.company}
                  onChange={onChange}
                  className="mt-1 w-full rounded-xl border border-gray-200 px-4 py-2.5"
                  placeholder="Acme Corp"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-800">
                Address
              </label>
              <input
                name="address"
                value={form.address}
                onChange={onChange}
                className="mt-1 w-full rounded-xl border border-gray-200 px-4 py-2.5"
                placeholder="123 Main St, Suite 100"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-800">
                  City
                </label>
                <input
                  name="city"
                  value={form.city}
                  onChange={onChange}
                  className="mt-1 w-full rounded-xl border border-gray-200 px-4 py-2.5"
                  placeholder="City"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-800">
                  State/Province
                </label>
                <input
                  name="state"
                  value={form.state}
                  onChange={onChange}
                  className="mt-1 w-full rounded-xl border border-gray-200 px-4 py-2.5"
                  placeholder="State"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-800">
                  Country
                </label>
                <input
                  name="country"
                  value={form.country}
                  onChange={onChange}
                  className="mt-1 w-full rounded-xl border border-gray-200 px-4 py-2.5"
                  placeholder="Country"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-800">
                Tax ID
              </label>
              <input
                name="tax_id"
                value={form.tax_id}
                onChange={onChange}
                className="mt-1 w-full rounded-xl border border-gray-200 px-4 py-2.5"
                placeholder="EIN / VAT / GST"
              />
            </div>

            {err ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-red-700 text-sm">
                {err}
              </div>
            ) : null}

            <div className="pt-2">
              <button
                type="submit"
                disabled={submitting}
                className="inline-flex items-center justify-center rounded-xl bg-indigo-600 px-5 py-2.5 font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {submitting ? "Creating account…" : "Create admin account"}
              </button>
            </div>
          </form>
        </div>

        <p className="mt-6 text-center text-sm text-gray-500">
          Already have an account?{" "}
          <button
            className="text-indigo-600 hover:underline"
            onClick={() => navigate("/login")}
          >
            Log in
          </button>
        </p>
      </div>
    </div>
  );
}
