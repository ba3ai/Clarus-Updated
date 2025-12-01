// src/pages/Login.jsx
import React, { useState, useContext } from "react";
import { useNavigate, Link } from "react-router-dom";
import { AuthContext } from "../context/AuthContext";
import api from "../services/api";

/**
 * Cookie-session login (SMS temporarily disabled)
 *
 * Backend (auth_routes.py) should:
 *  - POST /auth/login      → { ok: bool }  // no requires_sms for now
 *  - GET  /auth/me         → { ok: true, user: {...}, investor: {...}|null }
 */
export default function Login() {
  const navigate = useNavigate();
  const { setUser } = useContext(AuthContext);

  const [emailOrUsername, setEmailOrUsername] = useState("");
  const [password, setPassword] = useState("");

  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  // Single-step login: username + password
  const submitLogin = async (e) => {
    e.preventDefault();
    setStatus("");
    setLoading(true);

    try {
      const res = await api.post("/auth/login", {
        email: emailOrUsername,
        username: emailOrUsername, // backend accepts either
        password,
      });

      const data = res?.data || {};

      // Any non-ok result → treat as failure
      if (!data.ok) {
        throw new Error(
          data.error || "Invalid email/username or password"
        );
      }

      // Fully logged in → fetch profile then route
      await finishLoginAndRedirect();
    } catch (err) {
      console.error("Login error:", err);
      setStatus(err.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const finishLoginAndRedirect = async () => {
    try {
      const res = await api.get("/auth/me");
      const me = res?.data || {};

      if (!me.user) {
        console.error("Unexpected /auth/me payload:", me);
        throw new Error("Unable to load your profile after login.");
      }

      const u = me.user;

      // Normalize user into AuthContext
      const normalizedUser = {
        id: u.id,
        email: u.email,
        user_type: (u.user_type || "").toLowerCase(),
        full_name:
          u.name ||
          [u.first_name, u.last_name].filter(Boolean).join(" ") ||
          null,
        permission: u.permission || null,
      };

      setUser(normalizedUser);

      const role = normalizedUser.user_type;

      if (role === "admin") {
        navigate("/admin-dashboard");
      } else if (role === "groupadmin" || role === "investor") {
        // group admins should still see the investor dashboard UI
        navigate("/investor-dashboard");
      } else {
        throw new Error("Unauthorized user role.");
      }
    } catch (err) {
      console.error("getMe() failed after login:", err);
      throw new Error("Unable to load your profile after login.");
    }
  };

  return (
    <div className="min-h-screen grid place-items-center bg-emerald-500/90 p-6">
      <form
        onSubmit={submitLogin}
        className="w-full max-w-md rounded-2xl bg-white p-8 shadow-xl space-y-4"
      >
        <h1 className="text-2xl font-semibold text-center">Login</h1>

        {status && (
          <div className="rounded-lg bg-amber-50 border border-amber-200 text-amber-800 px-4 py-3 text-sm">
            {status}
          </div>
        )}

        <div>
          <label className="text-sm font-medium text-gray-700">
            Email or Username
          </label>
          <input
            className="mt-1 w-full rounded-lg border border-gray-200 px-4 py-2.5 outline-none focus:ring-4 focus:ring-emerald-100"
            value={emailOrUsername}
            onChange={(e) =>
              setEmailOrUsername(e.value || e.target.value)
            }
            autoComplete="username"
            required
          />
        </div>

        <div>
          <label className="text-sm font-medium text-gray-700">
            Password
          </label>
          <input
            type="password"
            className="mt-1 w-full rounded-lg border border-gray-200 px-4 py-2.5 outline-none focus:ring-4 focus:ring-emerald-100"
            value={password}
            onChange={(e) => setPassword(e.value || e.target.value)}
            autoComplete="current-password"
            required
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-emerald-600 text-white py-3 font-semibold hover:brightness-110 active:scale-[0.99] disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {loading ? "Signing in…" : "LOGIN"}
        </button>

        <div className="pt-1 text-center">
          <Link
            to="/forgot-password"
            className="inline-block text-sm text-emerald-700 hover:underline"
          >
            Forgot password?
          </Link>
        </div>
      </form>
    </div>
  );
}
