// frontend/src/components/tabs/Settings.jsx
import React, { useEffect, useState } from 'react';

const API_BASE = "/api/settings";
const ADMIN_USERS_API = "/api/admin/users";

/* ---------------- XSRF helpers (your version) ---------------- */

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
  // Only attach the XSRF header for non-GET or when explicitly requested
  if ((options.method && options.method !== "GET") || options.forceXsrf) {
    const token = getCookie("XSRF-TOKEN");
    if (token) headers.set("X-XSRF-TOKEN", token);
  }
  const res = await fetch(url, { ...options, headers, credentials: "include" });
  return res;
}

/* ---------------------------------------------------------------- */

export default function Settings() {
  // ===== Logo settings state (your original) =====
  const [loading, setLoading] = useState(false);
  const [logoUrl, setLogoUrl] = useState(null);
  const [file, setFile] = useState(null);
  const [message, setMessage] = useState("");

  // ===== Activity log state (from other dev) =====
  const [logs, setLogs] = useState([]);
  const [logLoading, setLogLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(25);
  const [total, setTotal] = useState(0);
  const [role, setRole] = useState("");
  const [action, setAction] = useState("");

  // ===== Account Controls state (from other dev) =====
  const [uSearch, setUSearch] = useState("");
  const [uRole, setURole] = useState("");
  const [uPage, setUPage] = useState(1);
  const [uPerPage, setUPerPage] = useState(25);
  const [uTotal, setUTotal] = useState(0);
  const [users, setUsers] = useState([]);
  const [doingId, setDoingId] = useState(null);
  const uTotalPages = Math.max(1, Math.ceil(uTotal / Math.max(1, uPerPage)));

  /* ================= Logo handlers ================= */

  const fetchLogo = async () => {
    setLoading(true);
    setMessage("");
    try {
      // include cookies so the backend can issue/set the CSRF cookie if needed
      const res = await xsrfFetch(`${API_BASE}/logo`, {
        method: "GET",
        forceXsrf: false,
      });
      const data = await res.json();
      setLogoUrl(data.url || null);
    } catch (e) {
      console.error(e);
      setMessage("Failed to load current logo.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogo();
  }, []);

  const onFileChange = (e) => setFile(e.target.files?.[0] || null);

  const onUpload = async (e) => {
    e.preventDefault();
    if (!file) {
      setMessage("Choose an image first.");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      // IMPORTANT: don't set Content-Type for FormData; let the browser set boundary
      const res = await xsrfFetch(`${API_BASE}/logo`, {
        method: "POST",
        body: fd,
      });
      let data = {};
      try {
        data = await res.json();
      } catch {}
      if (!res.ok) throw new Error(data.error || `Upload failed (${res.status})`);
      setLogoUrl(data.url);
      setFile(null);
      setMessage("Logo updated.");
    } catch (e) {
      console.error(e);
      setMessage(e.message === "Forbidden" ? "CSRF validation failed" : e.message);
    } finally {
      setLoading(false);
    }
  };

  const onRemove = async () => {
    if (!window.confirm("Remove the current logo?")) return;
    setLoading(true);
    setMessage("");
    try {
      const res = await xsrfFetch(`${API_BASE}/logo`, { method: "DELETE" });
      let data = {};
      try {
        data = await res.json();
      } catch {}
      if (!res.ok) throw new Error(data.error || `Remove failed (${res.status})`);
      setLogoUrl(null);
      setMessage("Logo removed.");
    } catch (e) {
      console.error(e);
      setMessage(e.message === "Forbidden" ? "CSRF validation failed" : e.message);
    } finally {
      setLoading(false);
    }
  };

  /* ================= Activity Log handlers ================= */

  const fetchActivity = async () => {
    setLogLoading(true);
    try {
      const qs = new URLSearchParams({ page, limit });
      if (role) qs.set("role", role);
      if (action) qs.set("action", action);

      const res = await xsrfFetch(`${API_BASE}/activity?${qs.toString()}`, {
        method: "GET",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to load activity");
      setLogs(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      console.error(e);
      setLogs([]);
      setTotal(0);
    } finally {
      setLogLoading(false);
    }
  };

  useEffect(() => {
    fetchActivity();
  }, [page, limit, role, action]);

  const totalPages = Math.max(1, Math.ceil(total / Math.max(1, limit)));

  /* ================= Account Controls handlers ================= */

  const fetchUsers = async (p = uPage) => {
    try {
      const qs = new URLSearchParams({ page: p, per_page: uPerPage });
      if (uSearch) qs.set("q", uSearch);
      if (uRole) qs.set("role", uRole);

      const res = await xsrfFetch(`${ADMIN_USERS_API}?${qs.toString()}`, {
        method: "GET",
      });

      if (res.status === 401 || res.status === 403) {
        console.warn("Account Controls: unauthorized. Are you logged in?");
        setUsers([]);
        setUTotal(0);
        return;
      }

      const data = await res.json();
      if (!res.ok || data.ok === false)
        throw new Error(data.error || "Failed to load users");

      setUsers(data.data || []);
      setUTotal(data.total || 0);
      setUPage(data.page || p);
    } catch (e) {
      console.error(e);
      setUsers([]);
      setUTotal(0);
    }
  };

  useEffect(() => {
    fetchUsers(1);
  }, [uSearch, uRole, uPerPage]);

  useEffect(() => {
    fetchUsers(uPage);
  }, [uPage]);

  const doAction = async (id, action, body) => {
    setDoingId(id);
    try {
      const res = await xsrfFetch(`${ADMIN_USERS_API}/${id}/${action}`, {
        method: "POST",
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });

      if (res.status === 401 || res.status === 403) {
        throw new Error("Not authorized. Please sign in again.");
      }

      const data = await res.json();
      if (!res.ok || data.ok === false)
        throw new Error(data.error || "Action failed");

      await fetchUsers(uPage);
      if (action === "send-reset" && data.url) {
        console.info("Password reset URL:", data.url);
      }
    } catch (e) {
      alert(e.message);
    } finally {
      setDoingId(null);
    }
  };

  /* ================= Render ================= */

  return (
    <div className="max-w-5xl space-y-6">
      <h2 className="text-xl font-semibold text-gray-800">Settings</h2>

      {/* Statement Branding */}
      <div className="bg-white border rounded-xl p-4 shadow-sm">
        <h3 className="text-base font-semibold mb-3">Statement Branding</h3>

        <div className="flex items-start gap-6">
          <div className="w-40 h-40 border rounded-md flex items-center justify-center bg-gray-50">
            {logoUrl ? (
              <img
                src={logoUrl}
                alt="Current logo"
                className="max-w-full max-h-full object-contain"
              />
            ) : (
              <span className="text-gray-400 text-sm">No Logo</span>
            )}
          </div>

          <form onSubmit={onUpload} className="flex-1 space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Upload New Logo
              </label>
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp,image/svg+xml"
                onChange={onFileChange}
                className="block w-full text-sm text-gray-700 file:mr-4 file:py-2 file:px-3 file:rounded-md file:border-0 file:bg-blue-600 file:text-white hover:file:bg-blue-700"
              />
              <p className="text-xs text-gray-500 mt-1">
                Recommended: transparent PNG, at least 200×200 px.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={loading}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {loading ? "Saving…" : "Save Logo"}
              </button>

              <button
                type="button"
                disabled={loading || !logoUrl}
                onClick={onRemove}
                className="px-4 py-2 bg-gray-100 text-gray-800 rounded-md hover:bg-gray-200 disabled:opacity-50"
              >
                Remove
              </button>

              <button
                type="button"
                onClick={fetchLogo}
                className="px-3 py-2 text-sm text-gray-600 hover:text-gray-900"
              >
                Refresh
              </button>
            </div>

            {message && <p className="text-sm text-gray-700">{message}</p>}
          </form>
        </div>
      </div>

      {/* Activity Log */}
      <div className="bg-white border rounded-xl p-4 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold">User Activity Log</h3>
          <div className="flex items-center gap-2">
            <select
              value={action}
              onChange={(e) => {
                setPage(1);
                setAction(e.target.value);
              }}
              className="border rounded px-2 py-1 text-sm"
            >
              <option value="">All actions</option>
              <option value="login">Login</option>
              <option value="logout">Logout</option>
            </select>

            <select
              value={role}
              onChange={(e) => {
                setPage(1);
                setRole(e.target.value);
              }}
              className="border rounded px-2 py-1 text-sm"
            >
              <option value="">All roles</option>
              <option value="admin">Admin</option>
              <option value="investor">Investor</option>
              <option value="groupadmin">Group admin</option>
            </select>

            <select
              value={limit}
              onChange={(e) => {
                setPage(1);
                setLimit(parseInt(e.target.value, 10));
              }}
              className="border rounded px-2 py-1 text-sm"
            >
              {[10, 25, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n}/page
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm border">
            <thead className="bg-gray-100">
              <tr>
                <th className="px-3 py-2 border">User</th>
                <th className="px-3 py-2 border">Role</th>
                <th className="px-3 py-2 border">Action</th>
                <th className="px-3 py-2 border">Date &amp; Time</th>
                <th className="px-3 py-2 border">IP</th>
              </tr>
            </thead>
            <tbody>
              {logLoading ? (
                <tr>
                  <td className="px-3 py-4 border text-center" colSpan={5}>
                    Loading…
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td className="px-3 py-4 border text-center" colSpan={5}>
                    No activity yet
                  </td>
                </tr>
              ) : (
                logs.map((r) => (
                  <tr key={r.id} className="hover:bg-gray-50">
                    <td className="px-3 py-2 border">
                      {r.name || r.user_id || "-"}
                    </td>
                    <td className="px-3 py-2 border">{r.role || "-"}</td>
                    <td className="px-3 py-2 border">
                      <span
                        className={
                          "px-2 py-1 rounded text-white " +
                          (r.action === "login"
                            ? "bg-green-500"
                            : "bg-rose-500")
                        }
                      >
                        {r.action}
                      </span>
                    </td>
                    <td className="px-3 py-2 border">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 border">{r.ip || "-"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="flex justify-between items-center mt-3">
          <p className="text-xs text-gray-500">
            Showing {logs.length} of {total} records
          </p>
          <div className="flex items-center gap-2">
            <button
              className="px-2 py-1 border rounded disabled:opacity-50"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              Prev
            </button>
            <span className="text-sm">
              Page {page} / {totalPages}
            </span>
            <button
              className="px-2 py-1 border rounded disabled:opacity-50"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </div>
      </div>

      {/* Account Controls */}
      <div className="bg-white border rounded-xl p-4 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold">Account Controls</h3>
          <div className="flex items-center gap-2">
            <input
              value={uSearch}
              onChange={(e) => setUSearch(e.target.value)}
              placeholder="Search name or email…"
              className="border rounded px-2 py-1 text-sm"
            />
            <select
              value={uRole}
              onChange={(e) => {
                setURole(e.target.value);
                setUPage(1);
              }}
              className="border rounded px-2 py-1 text-sm"
            >
              <option value="">All roles</option>
              <option value="admin">Admin</option>
              <option value="investor">Investor</option>
            </select>
            <select
              value={uPerPage}
              onChange={(e) => {
                setUPerPage(parseInt(e.target.value, 10));
                setUPage(1);
              }}
              className="border rounded px-2 py-1 text-sm"
            >
              {[10, 25, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n}/page
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm border">
            <thead className="bg-gray-100">
              <tr>
                <th className="px-3 py-2 border">User</th>
                <th className="px-3 py-2 border">Email</th>
                <th className="px-3 py-2 border">Role</th>
                <th className="px-3 py-2 border">Status</th>
                <th className="px-3 py-2 border text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.length === 0 ? (
                <tr>
                  <td className="px-3 py-4 border text-center" colSpan={5}>
                    No users found
                  </td>
                </tr>
              ) : (
                users.map((u) => (
                  <tr key={u.id} className="hover:bg-gray-50">
                    <td className="px-3 py-2 border">{u.name}</td>
                    <td className="px-3 py-2 border">{u.email}</td>
                    <td className="px-3 py-2 border capitalize">{u.role}</td>
                    <td className="px-3 py-2 border">
                      {u.is_blocked ? (
                        <span className="px-2 py-1 rounded bg-rose-100 text-rose-700">
                          Blocked
                        </span>
                      ) : (
                        <span className="px-2 py-1 rounded bg-green-100 text-green-700">
                          Active
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 border text-right">
                      {u.is_blocked ? (
                        <button
                          className="px-3 py-1 rounded bg-green-600 text-white disabled:opacity-50 mr-2"
                          disabled={doingId === u.id}
                          onClick={() => doAction(u.id, "unblock")}
                        >
                          Unblock
                        </button>
                      ) : (
                        <button
                          className="px-3 py-1 rounded bg-rose-600 text-white disabled:opacity-50 mr-2"
                          disabled={doingId === u.id}
                          onClick={() => {
                            const reason =
                              window.prompt(
                                "Reason for blocking (optional):"
                              ) || "";
                            doAction(u.id, "block", { reason });
                          }}
                        >
                          Block
                        </button>
                      )}
                      <button
                        className="px-3 py-1 rounded bg-indigo-600 text-white disabled:opacity-50"
                        disabled={doingId === u.id}
                        onClick={() => doAction(u.id, "send-reset")}
                      >
                        Send Reset
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="flex justify-between items-center mt-3">
          <p className="text-xs text-gray-500">
            Showing {users.length} of {uTotal} users
          </p>
          <div className="flex items-center gap-2">
            <button
              className="px-2 py-1 border rounded disabled:opacity-50"
              disabled={uPage <= 1}
              onClick={() => setUPage((p) => p - 1)}
            >
              Prev
            </button>
            <span className="text-sm">
              Page {uPage} / {uTotalPages}
            </span>
            <button
              className="px-2 py-1 border rounded disabled:opacity-50"
              disabled={uPage >= uTotalPages}
              onClick={() => setUPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
