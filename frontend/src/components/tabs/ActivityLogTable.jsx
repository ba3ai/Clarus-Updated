// frontend/src/components/settings/ActivityLogTable.jsx
import React, { useEffect, useMemo, useState } from "react";

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
  // Only attach XSRF header for non-GET or when explicitly forced
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

// Use relative base so it works with your Flask app behind the same origin
const API_BASE = "/api/settings";

export default function ActivityLogTable() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(25);
  const [total, setTotal] = useState(0);
  const [action, setAction] = useState("");
  const [role, setRole] = useState("");

  const fetchRows = async () => {
    setLoading(true);
    const qs = new URLSearchParams({ page, limit });
    if (action) qs.set("action", action);
    if (role) qs.set("role", role);

    try {
      const res = await xsrfFetch(
        `${API_BASE}/activity?${qs.toString()}`,
        { method: "GET" }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to load activity");
      setRows(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRows();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, limit, action, role]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(total / limit)),
    [total, limit]
  );

  return (
    <div className="border rounded-lg p-4 shadow-sm bg-white">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">User Activity Log</h2>
        <div className="flex gap-2">
          <select
            className="border rounded px-2 py-1 text-sm"
            value={action}
            onChange={(e) => {
              setPage(1);
              setAction(e.target.value);
            }}
          >
            <option value="">All actions</option>
            <option value="login">Login</option>
            <option value="logout">Logout</option>
          </select>
          <select
            className="border rounded px-2 py-1 text-sm"
            value={role}
            onChange={(e) => {
              setPage(1);
              setRole(e.target.value);
            }}
          >
            <option value="">All roles</option>
            <option value="admin">Admin</option>
            <option value="investor">Investor</option>
            <option value="groupadmin">Group admin</option>
          </select>
          <select
            className="border rounded px-2 py-1 text-sm"
            value={limit}
            onChange={(e) => {
              setPage(1);
              setLimit(parseInt(e.target.value, 10));
            }}
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
            {loading ? (
              <tr>
                <td className="px-3 py-4 border text-center" colSpan={5}>
                  Loading…
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td className="px-3 py-4 border text-center" colSpan={5}>
                  No activity yet
                </td>
              </tr>
            ) : (
              rows.map((r) => (
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
          Showing {rows.length} of {total} records
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
  );
}
