// src/components/tabs/AllAdmins.jsx
import React, { useEffect, useMemo, useState } from "react";
import AddAdmin from "./AddAdmin";

const ITEMS_PER_PAGE = 10;

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
    credentials: "include", // send session cookies
  });
}

// Backend route we already implemented: /api/admin/users
const ADMIN_USERS_API = "/api/admin/users";

export default function AllAdmins() {
  const [admins, setAdmins] = useState([]);
  const [filtered, setFiltered] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [page, setPage] = useState(1);
  const [showPopup, setShowPopup] = useState(false);

  const start = (page - 1) * ITEMS_PER_PAGE;
  const paginated = useMemo(
    () => filtered.slice(start, start + ITEMS_PER_PAGE),
    [filtered, start]
  );

  async function fetchAdmins() {
    setLoading(true);
    setErr("");
    try {
      const url = new URL(ADMIN_USERS_API, window.location.origin);
      url.searchParams.set("role", "admin");
      url.searchParams.set("page", "1");
      url.searchParams.set("per_page", "250");

      const res = await xsrfFetch(url.toString(), { method: "GET" });
      const data = await res.json().catch(() => ({}));

      if (!res.ok || data.ok === false) {
        throw new Error(data.error || `Failed to load admins (${res.status})`);
      }

      const list = Array.isArray(data.data) ? data.data : [];
      setAdmins(list);
      setFiltered(list);
    } catch (e) {
      setErr(e.message || "Failed to load admins.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchAdmins();
  }, []);

  useEffect(() => {
    const q = search.trim().toLowerCase();
    const f = admins.filter((u) => {
      const name = (
        u.name || `${u.first_name || ""} ${u.last_name || ""}`
      ).trim();
      return (
        name.toLowerCase().includes(q) ||
        (u.email || "").toLowerCase().includes(q)
      );
    });
    setFiltered(f);
    setPage(1);
  }, [search, admins]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / ITEMS_PER_PAGE));

  if (loading) return <p className="mt-6 text-center">Loading admins…</p>;
  if (err) return <p className="mt-6 text-center text-red-600">{err}</p>;

  return (
    <div className="p-4">
      {/* Header row */}
      <div className="mb-6 flex flex-col sm:flex-row gap-4 sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-gray-800">All Admins</h1>

        <div className="flex w-full sm:w-auto gap-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="🔍 Search by name or email"
            className="flex-1 sm:w-80 px-4 py-2 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={() => setShowPopup(true)}
            className="bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800 text-white font-semibold px-5 py-2 rounded-lg shadow-md"
          >
            + Add New Admin
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="min-w-full bg-white border border-gray-200 rounded-lg shadow">
          <thead className="bg-blue-600 text-white">
            <tr>
              <th className="px-4 py-2 text-left">Name</th>
              <th className="px-4 py-2 text-left">Email</th>
              <th className="px-4 py-2 text-left">Bank</th>
              <th className="px-4 py-2 text-left">Status</th>
              <th className="px-4 py-2 text-left">Permission</th>
            </tr>
          </thead>
          <tbody>
            {paginated.length === 0 ? (
              <tr>
                <td colSpan="5" className="text-center p-4">
                  No admins found.
                </td>
              </tr>
            ) : (
              paginated.map((u) => {
                const name = (
                  u.name || `${u.first_name || ""} ${u.last_name || ""}`
                ).trim();
                return (
                  <tr
                    key={u.id || u.email}
                    className="border-b hover:bg-gray-50"
                  >
                    <td className="px-4 py-2">{name || "-"}</td>
                    <td className="px-4 py-2">{u.email || "-"}</td>
                    <td className="px-4 py-2">{u.bank || "-"}</td>
                    <td className="px-4 py-2">{u.status || "-"}</td>
                    <td className="px-4 py-2">{u.permission || "-"}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="text-sm text-gray-500 mt-4">
        Showing {paginated.length} of {filtered.length} admins
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-4 flex justify-center items-center gap-4">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-4 py-2 border rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-50"
          >
            ◀ Prev
          </button>
          <span className="text-gray-700 font-semibold">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-4 py-2 border rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-50"
          >
            Next ▶
          </button>
        </div>
      )}

      {/* Add Admin Popup */}
      {showPopup && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="relative w-full max-w-3xl">
            <button
              onClick={() => setShowPopup(false)}
              className="absolute -top-3 -right-3 bg-white text-gray-600 px-3 py-1 rounded-full shadow"
              aria-label="Close"
            >
              ✖
            </button>
            <div className="bg-white rounded-lg overflow-hidden shadow-lg max-h-[90vh] overflow-y-auto">
              <AddAdmin
                onSuccess={() => {
                  setShowPopup(false);
                  fetchAdmins();
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
