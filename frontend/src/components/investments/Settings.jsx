// src/pages/investments/Settings.jsx
import React, { useState } from "react";
import api from "../../services/api";

const API_BASE = import.meta.env.VITE_API_BASE || "https://clarus.azurewebsites.net";

export default function Settings() {
  /* ---------------------- Change password state (YOUR BASE) ---------------------- */
  const [showModal, setShowModal] = useState(false);
  const [step, setStep] = useState(1); // 1: email, 2: code, 3: new password

  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const resetState = () => {
    setStep(1);
    setEmail("");
    setCode("");
    setPassword("");
    setConfirm("");
    setError("");
    setInfo("");
  };

  const openModal = () => {
    resetState();
    setShowModal(true);
  };

  const closeModal = () => {
    setShowModal(false);
  };

  // STEP 1: send 6-digit code
  const handleSendCode = async (e) => {
    e.preventDefault();
    setError("");
    setInfo("");
    if (!email.trim()) {
      setError("Email is required");
      return;
    }
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/auth/password/code/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j?.msg || "Unable to send code");
      setInfo("If this email exists, a 6-digit code has been sent.");
      setStep(2);
    } catch (err) {
      setError(err.message || "Unable to send code");
    } finally {
      setLoading(false);
    }
  };

  // STEP 2: verify code
  const handleVerifyCode = async (e) => {
    e.preventDefault();
    setError("");
    setInfo("");
    if (!code.trim()) {
      setError("Verification code is required");
      return;
    }
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/auth/password/code/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j?.msg || "Invalid or expired code");
      setInfo("Code verified. You can now choose a new password.");
      setStep(3);
    } catch (err) {
      setError(err.message || "Invalid or expired code");
    } finally {
      setLoading(false);
    }
  };

  // STEP 3: change password
  const handleChangePassword = async (e) => {
    e.preventDefault();
    setError("");
    setInfo("");

    if (!password || !confirm) {
      setError("Please enter and confirm your new password.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/auth/password/code/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code, password, confirm }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j?.msg || "Unable to update password");

      setInfo("Password updated. Redirecting to login…");

      // Clear any auth tokens and redirect to login
      localStorage.removeItem("accessToken");
      localStorage.removeItem("access_token");
      localStorage.removeItem("token");
      setTimeout(() => {
        window.location.href = "/login";
      }, 1000);
    } catch (err) {
      setError(err.message || "Unable to update password");
    } finally {
      setLoading(false);
    }
  };

  /* ----------------- Dependent Investor state (MERGED FROM 2ND FILE) ----------------- */
  const [showDepModal, setShowDepModal] = useState(false);
  const [depName, setDepName] = useState("");
  const [depEmail, setDepEmail] = useState("");
  const [depLoading, setDepLoading] = useState(false);
  const [depError, setDepError] = useState("");
  const [depInfo, setDepInfo] = useState("");

  const resetDepState = (keepInfo = false) => {
    setDepName("");
    setDepEmail("");
    setDepError("");
    if (!keepInfo) setDepInfo("");
    setDepLoading(false);
  };

  const openDepModal = () => {
    resetDepState(false);
    setShowDepModal(true);
  };

  const closeDepModal = () => {
    setShowDepModal(false);
    resetDepState(false);
  };

  const handleDependentSubmit = async (e) => {
    e.preventDefault();
    setDepError("");
    setDepInfo("");

    const name = depName.trim();
    const emailVal = depEmail.trim().toLowerCase();

    if (!name || !emailVal) {
      setDepError("Please provide both Investor Name and Investor Email.");
      return;
    }

    try {
      setDepLoading(true);
      const { data } = await api.post(
        "/investor/dependents/request",
        {
          investor_name: name,
          investor_email: emailVal,
        },
        { headers: { "Content-Type": "application/json" } }
      );

      const msg =
        data?.message ||
        data?.msg ||
        "Request sent. An admin will review it shortly.";

      setDepInfo(msg);
      resetDepState(true); // clear inputs, keep message
    } catch (err) {
      setDepError(
        err?.response?.data?.error ||
          err?.response?.data?.message ||
          err.message ||
          "Unable to send request."
      );
    } finally {
      setDepLoading(false);
    }
  };

  /* -------------------- Group Investor state (MERGED FROM 2ND FILE) ------------------ */
  const [showGroupModal, setShowGroupModal] = useState(false);
  const [groupName, setGroupName] = useState("");
  const [groupEmail, setGroupEmail] = useState("");
  const [groupLoading, setGroupLoading] = useState(false);
  const [groupError, setGroupError] = useState("");
  const [groupInfo, setGroupInfo] = useState("");

  const resetGroupState = (keepInfo = false) => {
    setGroupName("");
    setGroupEmail("");
    setGroupError("");
    if (!keepInfo) setGroupInfo("");
    setGroupLoading(false);
  };

  const openGroupModal = () => {
    resetGroupState(false);
    setShowGroupModal(true);
  };

  const closeGroupModal = () => {
    setShowGroupModal(false);
    resetGroupState(false);
  };

  const handleSubmitGroupRequest = async (e) => {
    e.preventDefault();
    setGroupError("");
    setGroupInfo("");

    const name = groupName.trim();
    const emailVal = groupEmail.trim().toLowerCase();

    if (!name || !emailVal) {
      setGroupError("Please provide both Investor Name and Investor Email.");
      return;
    }

    try {
      setGroupLoading(true);
      const { data } = await api.post(
        "/investor/group-investor/request",
        {
          investor_name: name,
          investor_email: emailVal,
        },
        { headers: { "Content-Type": "application/json" } }
      );

      const msg =
        data?.message ||
        data?.msg ||
        "Your request to become a Group Investor Admin has been submitted.";

      setGroupInfo(msg);
      resetGroupState(true); // clear inputs, keep message
    } catch (err) {
      setGroupError(
        err?.response?.data?.error ||
          err?.response?.data?.message ||
          err.message ||
          "Unable to submit request."
      );
    } finally {
      setGroupLoading(false);
    }
  };

  /* -------------------------------- RENDER --------------------------------- */

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-slate-800">Settings</h2>
        <p className="text-sm text-slate-500">
          Manage your investor account preferences.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-1 max-w-2xl">
        {/* Security card (password change) */}
        <section className="rounded-xl border bg-white shadow-sm p-4 space-y-3">
          <h3 className="font-semibold text-slate-800 text-sm">Security</h3>
          <p className="text-xs text-slate-500">
            We recommend changing your password regularly.
          </p>
          <button
            type="button"
            onClick={openModal}
            className="inline-flex items-center justify-center rounded-lg bg-indigo-600 text-white text-sm font-medium px-4 py-2 mt-2 hover:brightness-110"
          >
            Change password
          </button>
        </section>

        {/* Dependent Investors */}
        <section className="rounded-xl border bg-white shadow-sm p-4 space-y-3">
          <h3 className="font-semibold text-slate-800 text-sm">
            Dependent Investors
          </h3>
          <p className="text-xs text-slate-500">
            Add an existing investor as your dependent. Your request will be
            reviewed and approved by an administrator.
          </p>
          <button
            type="button"
            onClick={openDepModal}
            className="inline-flex items-center justify-center rounded-lg bg-sky-600 text-white text-sm font-medium px-4 py-2 mt-2 hover:brightness-110"
          >
            Add Dependent Investor
          </button>
        </section>

        {/* Group Investor */}
        <section className="rounded-xl border bg-white shadow-sm p-4 space-y-3">
          <h3 className="font-semibold text-slate-800 text-sm">
            Group Investor
          </h3>
          <p className="text-xs text-slate-500">
            Request to become a Group Investor Admin. Enter the investor you
            want to include in your group. Your request will be reviewed by an
            administrator.
          </p>
          <button
            type="button"
            onClick={openGroupModal}
            className="inline-flex items-center justify-center rounded-lg bg-emerald-600 text-white text-sm font-medium px-4 py-2 mt-2 hover:brightness-110"
          >
            Create Group Investor
          </button>
        </section>
      </div>

      {/* Footer note */}
      <p className="text-xs text-slate-400">
        You can wire additional controls to real API endpoints as they are
        implemented.
      </p>

      {/* ---------------- PASSWORD MODAL (your original flow) ---------------- */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
          <div className="w-full max-w-md rounded-2xl bg-white shadow-xl p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-800">
                Change password
              </h3>
              <button
                type="button"
                onClick={closeModal}
                className="text-slate-400 hover:text-slate-600 text-xl leading-none"
              >
                ×
              </button>
            </div>

            {/* Step indicator */}
            <p className="text-xs text-slate-500">Step {step} of 3</p>

            {error && (
              <div className="rounded-md border border-rose-200 bg-rose-50 text-rose-700 px-3 py-2 text-sm">
                {error}
              </div>
            )}
            {info && (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 text-emerald-700 px-3 py-2 text-sm">
                {info}
              </div>
            )}

            {step === 1 && (
              <form onSubmit={handleSendCode} className="space-y-4">
                <div className="space-y-1">
                  <label className="text-sm font-medium text-slate-700">
                    Email address
                  </label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full rounded-lg border px-3 py-2 text-sm bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-100 border-gray-300"
                    placeholder="you@example.com"
                    required
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full inline-flex items-center justify-center rounded-lg bg-indigo-600 text-white text-sm font-medium px-4 py-2 hover:brightness-110 disabled:opacity-60"
                >
                  {loading ? "Sending code…" : "Send verification code"}
                </button>
              </form>
            )}

            {step === 2 && (
              <form onSubmit={handleVerifyCode} className="space-y-4">
                <div className="space-y-1">
                  <label className="text-sm font-medium text-slate-700">
                    Verification code
                  </label>
                  <input
                    type="text"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    className="w-full rounded-lg border px-3 py-2 text-sm bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-100 border-gray-300 tracking-[0.2em]"
                    placeholder="123456"
                    required
                  />
                  <p className="text-xs text-slate-500">
                    Enter the 6-digit code sent to <strong>{email}</strong>.
                  </p>
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full inline-flex items-center justify-center rounded-lg bg-indigo-600 text-white text-sm font-medium px-4 py-2 hover:brightness-110 disabled:opacity-60"
                >
                  {loading ? "Verifying…" : "Verify code"}
                </button>
              </form>
            )}

            {step === 3 && (
              <form onSubmit={handleChangePassword} className="space-y-4">
                <div className="space-y-1">
                  <label className="text-sm font-medium text-slate-700">
                    New password
                  </label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full rounded-lg border px-3 py-2 text-sm bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-100 border-gray-300"
                    required
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium text-slate-700">
                    Confirm new password
                  </label>
                  <input
                    type="password"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    className="w-full rounded-lg border px-3 py-2 text-sm bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-100 border-gray-300"
                    required
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full inline-flex items-center justify-center rounded-lg bg-indigo-600 text-white text-sm font-medium px-4 py-2 hover:brightness-110 disabled:opacity-60"
                >
                  {loading ? "Updating…" : "Update password"}
                </button>
              </form>
            )}
          </div>
        </div>
      )}

      {/* ------------------- ADD DEPENDENT INVESTOR MODAL ------------------- */}
      {showDepModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
          <div className="w-full max-w-md rounded-2xl bg-white shadow-xl p-6 space-y-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-900">
                Add Dependent Investor
              </h3>
              <button
                type="button"
                onClick={closeDepModal}
                className="text-slate-400 hover:text-slate-600 text-xl leading-none"
              >
                ×
              </button>
            </div>

            {depError && (
              <div className="rounded-md border border-rose-200 bg-rose-50 text-rose-700 px-3 py-2 text-sm">
                {depError}
              </div>
            )}
            {depInfo && (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 text-emerald-700 px-3 py-2 text-sm">
                {depInfo}
              </div>
            )}

            <form onSubmit={handleDependentSubmit} className="space-y-4">
              <div className="space-y-1">
                <label className="text-sm font-medium text-slate-700">
                  Investor Name
                </label>
                <input
                  type="text"
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100 border-gray-300"
                  value={depName}
                  onChange={(e) => setDepName(e.target.value)}
                  placeholder="Full name as on the account"
                />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium text-slate-700">
                  Investor Email
                </label>
                <input
                  type="email"
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100 border-gray-300"
                  value={depEmail}
                  onChange={(e) => setDepEmail(e.target.value)}
                  placeholder="their.email@example.com"
                />
              </div>

              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={closeDepModal}
                  className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={depLoading}
                  className="inline-flex items-center justify-center rounded-lg bg-sky-600 text-white text-sm font-medium px-4 py-2 hover:brightness-110 disabled:opacity-60"
                >
                  {depLoading ? "Sending…" : "Send Request"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* -------------------- CREATE GROUP INVESTOR MODAL ------------------- */}
      {showGroupModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
          <div className="w-full max-w-md rounded-2xl bg-white shadow-xl p-6 space-y-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-900">
                Create Group Investor
              </h3>
              <button
                type="button"
                onClick={closeGroupModal}
                className="text-slate-400 hover:text-slate-600 text-xl leading-none"
              >
                ×
              </button>
            </div>

            <p className="text-xs text-slate-500">
              Enter the investor you want to include in your group. You can send
              multiple requests to add more investors.
            </p>

            {groupError && (
              <div className="rounded-md border border-rose-200 bg-rose-50 text-rose-700 px-3 py-2 text-sm">
                {groupError}
              </div>
            )}
            {groupInfo && (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 text-emerald-700 px-3 py-2 text-sm">
                {groupInfo}
              </div>
            )}

            <form onSubmit={handleSubmitGroupRequest} className="space-y-4">
              <div className="space-y-1">
                <label className="text-sm font-medium text-slate-700">
                  Investor Name
                </label>
                <input
                  type="text"
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-emerald-100 border-gray-300"
                  placeholder="Full name as on the account"
                  value={groupName}
                  onChange={(e) => setGroupName(e.target.value)}
                />
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium text-slate-700">
                  Investor Email
                </label>
                <input
                  type="email"
                  className="w-full rounded-lg border px-3 py-2 text-sm bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-emerald-100 border-gray-300"
                  placeholder="their.email@example.com"
                  value={groupEmail}
                  onChange={(e) => setGroupEmail(e.target.value)}
                />
              </div>

              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={closeGroupModal}
                  className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={groupLoading}
                  className="inline-flex items-center justify-center rounded-lg bg-emerald-600 text-white text-sm font-medium px-4 py-2 hover:brightness-110 disabled:opacity-60"
                >
                  {groupLoading ? "Submitting…" : "Submit Request"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
