// src/components/tabs/AccountControls.jsx
import React, { useEffect, useState } from "react";

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
  // Only attach XSRF for non-GET requests, or when explicitly forced
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

const ADMIN_USERS_API = "/api/admin/users";

export default function AccountControls() {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [role, setRole] = useState(""); // '', 'admin', 'investor'
  const [busyId, setBusyId] = useState(null);
  const [page, setPage] = useState(1);
  const [meta, setMeta] = useState({ page: 1, pages: 1, total: 0 });

  async function load(p = page) {
    const url = new URL(ADMIN_USERS_API, window.location.origin);
    if (q) url.searchParams.set("q", q);
    if (role) url.searchParams.set("role", role);
    url.searchParams.set("page", p);
    url.searchParams.set("per_page", "25");

    try {
      const res = await xsrfFetch(url.toString(), { method: "GET" });
      const data = await res.json();
      if (res.ok && data.ok) {
        setRows(data.data || []);
        setMeta({ page: data.page, pages: data.pages, total: data.total });
        setPage(data.page);
      } else {
        console.error("Failed to load users", data);
      }
    } catch (err) {
      console.error("AccountControls load error:", err);
    }
  }

  useEffect(() => {
    load(1); // initial
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const t = setTimeout(() => load(1), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, role]);

  async function act(id, action, body) {
    setBusyId(id);
    try {
      const res = await xsrfFetch(`${ADMIN_USERS_API}/${id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : null,
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "Action failed");
      await load(page);
    } catch (e) {
      alert(e.message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="mt-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold">Account Controls</h3>
        <div className="flex gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name or email..."
            className="border rounded px-3 py-1"
          />
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="border rounded px-2 py-1"
          >
            <option value="">All roles</option>
            <option value="admin">Admin</option>
            <option value="investor">Investor</option>
          </select>
        </div>
      </div>

      <div className="overflow-auto border rounded">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left">User</th>
              <th className="px-3 py-2">Email</th>
              <th className="px-3 py-2">Role</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u) => (
              <tr key={u.id} className="border-t">
                <td className="px-3 py-2 text-left">{u.name}</td>
                <td className="px-3 py-2">{u.email}</td>
                <td className="px-3 py-2 capitalize">{u.role}</td>
                <td className="px-3 py-2">
                  {u.is_blocked ? (
                    <span className="inline-block px-2 py-0.5 rounded bg-red-100 text-red-700">
                      Blocked
                    </span>
                  ) : (
                    <span className="inline-block px-2 py-0.5 rounded bg-green-100 text-green-700">
                      Active
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  {u.is_blocked ? (
                    <button
                      className="px-3 py-1 rounded bg-green-600 text-white disabled:opacity-50 mr-2"
                      disabled={busyId === u.id}
                      onClick={() => act(u.id, "unblock")}
                    >
                      Unblock
                    </button>
                  ) : (
                    <button
                      className="px-3 py-1 rounded bg-red-600 text-white disabled:opacity-50 mr-2"
                      disabled={busyId === u.id}
                      onClick={() => {
                        const reason =
                          window.prompt(
                            "Reason for blocking (optional):"
                          ) || "";
                        act(u.id, "block", { reason });
                      }}
                    >
                      Block
                    </button>
                  )}
                  <button
                    className="px-3 py-1 rounded bg-indigo-600 text-white disabled:opacity-50"
                    disabled={busyId === u.id}
                    onClick={() => act(u.id, "send-reset")}
                  >
                    Send Reset
                  </button>
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td
                  className="px-3 py-6 text-center text-gray-500"
                  colSpan={5}
                >
                  No users found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between mt-3">
        <span className="text-sm text-gray-500">
          Page {meta.page} / {meta.pages} — {meta.total} users
        </span>
        <div className="flex gap-2">
          <button
            disabled={page <= 1}
            onClick={() => load(page - 1)}
            className="px-3 py-1 border rounded disabled:opacity-50"
          >
            Prev
          </button>
          <button
            disabled={page >= meta.pages}
            onClick={() => load(page + 1)}
            className="px-3 py-1 border rounded disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
