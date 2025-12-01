// frontend/src/components/tabs/GroupInvestorAdmin.jsx
import React, { useEffect, useState } from "react";
import { Plus, X, Edit2, Trash2, UserPlus } from "lucide-react";

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
    credentials: "include", // send Flask session cookie
  });
}

export default function GroupInvestorAdmin() {
  const [groupAdmins, setGroupAdmins] = useState([]);
  const [error, setError] = useState("");
  const [loadingAdmins, setLoadingAdmins] = useState(false);

  // expanded row (clicking the admin name)
  const [expandedAdminId, setExpandedAdminId] = useState(null);
  const [membersByAdmin, setMembersByAdmin] = useState({}); // { [adminId]: members[] }
  const [loadingMembersFor, setLoadingMembersFor] = useState(null);

  // "Add Investor to Group" modal state
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [modalAdmin, setModalAdmin] = useState(null);
  const [availableInvestors, setAvailableInvestors] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]); // array of investor IDs
  const [loadingAvailable, setLoadingAvailable] = useState(false);
  const [saving, setSaving] = useState(false);

  // "Add Group Investor Admin" modal state
  const [isAddAdminModalOpen, setIsAddAdminModalOpen] = useState(false);
  const [investorUsers, setInvestorUsers] = useState([]); // candidate users
  const [selectedAdminUserId, setSelectedAdminUserId] = useState("");
  const [loadingInvestorUsers, setLoadingInvestorUsers] = useState(false);
  const [savingAdmin, setSavingAdmin] = useState(false);

  // ---------------------------------------------------------------------------
  // Load initial group admin list (from /api/admin/users, then filter)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    fetchGroupAdmins();
  }, []);

  const fetchGroupAdmins = async () => {
    setLoadingAdmins(true);
    setError("");
    try {
      // Get all users (or a large page) and filter by role === "group admin"
      const res = await xsrfFetch("/api/admin/users?per_page=500", {
        method: "GET",
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(data.error || `Failed to load users (${res.status})`);
      }

      const allUsers = Array.isArray(data.data) ? data.data : [];
      const ga = allUsers.filter((u) =>
        (u.role || "").toLowerCase().includes("group")
      );
      setGroupAdmins(ga);
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to load Group Investor Admins");
    } finally {
      setLoadingAdmins(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Load members for a given admin (shown when row is expanded)
  // ---------------------------------------------------------------------------
  const fetchMembersForAdmin = async (adminId) => {
    setLoadingMembersFor(adminId);
    setError("");
    try {
      const res = await xsrfFetch(
        `/api/admin/group-admins/${adminId}/investors`,
        { method: "GET" }
      );

      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(
          data.message || `Failed to load members (${res.status})`
        );
      }

      setMembersByAdmin((prev) => ({
        ...prev,
        [adminId]: data.members || [],
      }));
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to load group members");
    } finally {
      setLoadingMembersFor(null);
    }
  };

  // ---------------------------------------------------------------------------
  // Open "Add Investor" modal for a specific Group Admin
  // ---------------------------------------------------------------------------
  const openAddModal = async (admin) => {
    setModalAdmin(admin);
    setIsAddModalOpen(true);
    setSelectedIds([]);
    await fetchAvailableInvestors(admin.id);
  };

  const closeAddModal = () => {
    setIsAddModalOpen(false);
    setModalAdmin(null);
    setAvailableInvestors([]);
    setSelectedIds([]);
  };

  // Load investors that are available for this admin
  const fetchAvailableInvestors = async (adminId) => {
    setLoadingAvailable(true);
    setError("");
    try {
      const res = await xsrfFetch(
        `/api/admin/group-admins/${adminId}/available-investors`,
        { method: "GET" }
      );

      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(
          data.message ||
            `Failed to load available investors (${res.status})`
        );
      }

      setAvailableInvestors(data.investors || []);
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to load available investors");
    } finally {
      setLoadingAvailable(false);
    }
  };

  const toggleSelectInvestor = (investorId) => {
    setSelectedIds((prev) =>
      prev.includes(investorId)
        ? prev.filter((id) => id !== investorId)
        : [...prev, investorId]
    );
  };

  // ---------------------------------------------------------------------------
  // Add selected investors to group ("Add Selected" button)
  // ---------------------------------------------------------------------------
  const handleAddSelected = async (e) => {
    e.preventDefault();
    if (!modalAdmin || selectedIds.length === 0) return;

    setSaving(true);
    setError("");

    try {
      const res = await xsrfFetch(
        `/api/admin/group-admins/${modalAdmin.id}/investors`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ investor_ids: selectedIds }),
        }
      );

      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(
          data.message ||
            `Failed to add investors to group (status ${res.status})`
        );
      }

      await fetchMembersForAdmin(modalAdmin.id);
      closeAddModal();
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to add investors to group");
    } finally {
      setSaving(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Remove investor from group
  // ---------------------------------------------------------------------------
  const handleRemoveMember = async (adminId, investorId) => {
    if (!window.confirm("Remove this investor from the group?")) return;

    try {
      const res = await xsrfFetch(
        `/api/admin/group-admins/${adminId}/investors/${investorId}`,
        { method: "DELETE" }
      );

      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(
          data.message ||
            `Failed to remove investor from group (status ${res.status})`
        );
      }

      await fetchMembersForAdmin(adminId);
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to remove investor from group");
    }
  };

  // ---------------------------------------------------------------------------
  // Delete group admin
  // ---------------------------------------------------------------------------
  const handleDeleteAdmin = async (adminId) => {
    if (!window.confirm("Delete this Group Investor Admin?")) return;

    try {
      const res = await xsrfFetch(
        `/api/admin/group-investor-admin/${adminId}`,
        { method: "DELETE" }
      );
      const data = await res.json().catch(() => ({}));

      if (!res.ok || data.ok === false) {
        throw new Error(
          data.message ||
            `Failed to delete Group Investor Admin (status ${res.status})`
        );
      }

      setGroupAdmins((prev) => prev.filter((ga) => ga.id !== adminId));
      setMembersByAdmin((prev) => {
        const copy = { ...prev };
        delete copy[adminId];
        return copy;
      });
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to delete Group Investor Admin");
    }
  };

  // ---------------------------------------------------------------------------
  // "Add Group Investor Admin" – fetch investor users and create admin
  // ---------------------------------------------------------------------------
  const openAddAdminModal = async () => {
    setIsAddAdminModalOpen(true);
    setSelectedAdminUserId("");
    await fetchInvestorUsers();
  };

  const closeAddAdminModal = () => {
    setIsAddAdminModalOpen(false);
    setInvestorUsers([]);
    setSelectedAdminUserId("");
  };

  const fetchInvestorUsers = async () => {
    setLoadingInvestorUsers(true);
    setError("");
    try {
      const res = await xsrfFetch("/api/admin/investors", { method: "GET" });

      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(
          data.message || `Failed to load investors (${res.status})`
        );
      }

      setInvestorUsers(data.investors || []);
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to load investors for admin selection");
    } finally {
      setLoadingInvestorUsers(false);
    }
  };

  const handleCreateGroupAdmin = async (e) => {
    e.preventDefault();
    if (!selectedAdminUserId) return;

    setSavingAdmin(true);
    setError("");

    try {
      const res = await xsrfFetch("/api/admin/group-investor-admin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ investor_id: selectedAdminUserId }),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(
          data.message ||
            `Failed to create Group Investor Admin (status ${res.status})`
        );
      }

      await fetchGroupAdmins();
      closeAddAdminModal();
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to create Group Investor Admin");
    } finally {
      setSavingAdmin(false);
    }
  };

  // ---------------------------------------------------------------------------
  // UI helpers
  // ---------------------------------------------------------------------------
  const toggleExpandAdmin = (adminId) => {
    setExpandedAdminId((prev) => (prev === adminId ? null : adminId));
    if (!membersByAdmin[adminId]) {
      fetchMembersForAdmin(adminId);
    }
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">
          Group Investor Admin
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Manage investor groups, assign admins, and control group-level access.
        </p>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-800">
            Group Investor Admins
          </h2>
          <button
            type="button"
            onClick={openAddAdminModal}
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-blue-700"
          >
            <Plus size={14} />
            Add Group Investor Admin
          </button>
        </div>

        {loadingAdmins ? (
          <p className="text-sm text-gray-500">Loading group admins...</p>
        ) : groupAdmins.length === 0 ? (
          <p className="text-sm text-gray-500">
            No Group Investor Admins yet. Click{" "}
            <span className="font-semibold">“Add Group Investor Admin”</span>{" "}
            to create one.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b bg-gray-50 text-xs font-semibold uppercase text-gray-500">
                  <th className="px-3 py-2 text-left">Name</th>
                  <th className="px-3 py-2 text-left">Email</th>
                  <th className="px-3 py-2 text-left">Created</th>
                  <th className="px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {groupAdmins.map((admin) => {
                  const members = membersByAdmin[admin.id] || [];
                  const isExpanded = expandedAdminId === admin.id;

                  return (
                    <React.Fragment key={admin.id}>
                      <tr className="border-b">
                        <td className="px-3 py-2 whitespace-nowrap">
                          <button
                            type="button"
                            onClick={() => toggleExpandAdmin(admin.id)}
                            className="text-blue-600 hover:underline"
                          >
                            {admin.name || "—"}
                          </button>
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {admin.email || "—"}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap text-gray-500">
                          —
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => openAddModal(admin)}
                              className="inline-flex items-center gap-1 rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
                            >
                              <UserPlus size={14} />
                              Add Investor
                            </button>

                            <button
                              type="button"
                              onClick={() =>
                                alert(
                                  "TODO: edit logic for Group Investor Admin"
                                )
                              }
                              className="inline-flex items-center gap-1 rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
                            >
                              <Edit2 size={14} />
                              Edit
                            </button>

                            <button
                              type="button"
                              onClick={() => handleDeleteAdmin(admin.id)}
                              className="inline-flex items-center gap-1 rounded-md border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                            >
                              <Trash2 size={14} />
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>

                      {isExpanded && (
                        <tr className="border-b bg-gray-50">
                          <td
                            className="px-3 py-3 text-sm text-gray-700"
                            colSpan={4}
                          >
                            <div className="font-semibold mb-2">
                              Investors in this group
                            </div>
                            {loadingMembersFor === admin.id ? (
                              <div className="text-gray-500">
                                Loading investors...
                              </div>
                            ) : members.length === 0 ? (
                              <div className="text-gray-500">
                                No investors in this group yet. Use{" "}
                                <span className="font-semibold">
                                  “Add Investor”
                                </span>{" "}
                                to add one or more.
                              </div>
                            ) : (
                              <ul className="space-y-1">
                                {members.map((m) => (
                                  <li
                                    key={m.investor_id}
                                    className="flex items-center justify-between"
                                  >
                                    <span>
                                      {m.name || "—"}{" "}
                                      <span className="text-gray-500">
                                        ({m.email || "—"})
                                      </span>
                                    </span>
                                    <button
                                      type="button"
                                      onClick={() =>
                                        handleRemoveMember(
                                          admin.id,
                                          m.investor_id
                                        )
                                      }
                                      className="text-xs text-red-600 hover:text-red-800"
                                    >
                                      Remove
                                    </button>
                                  </li>
                                ))}
                              </ul>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Add Investors to Group Modal */}
      {isAddModalOpen && modalAdmin && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30">
          <div className="bg-white rounded-lg shadow-lg w-full max-w-xl">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <h3 className="text-sm font-semibold">
                Add Investors to Group –{" "}
                <span className="font-bold">
                  {modalAdmin.name || modalAdmin.email}
                </span>
              </h3>
              <button
                type="button"
                onClick={closeAddModal}
                className="text-gray-400 hover:text-gray-600"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleAddSelected}>
              <div className="max-h-80 overflow-y-auto px-4 py-3 space-y-2">
                <p className="text-xs text-gray-500 mb-2">
                  Select one or more investors to add under this Group Investor
                  Admin. Investors who are already in this group are not shown.
                </p>

                {loadingAvailable ? (
                  <div className="text-sm text-gray-500">
                    Loading investors...
                  </div>
                ) : availableInvestors.length === 0 ? (
                  <div className="text-sm text-gray-500">
                    No available investors to add.
                  </div>
                ) : (
                  availableInvestors.map((inv) => (
                    <label
                      key={inv.id}
                      className="flex items-center gap-2 rounded-md border border-gray-200 px-3 py-2 text-sm hover:bg-gray-50"
                    >
                      <input
                        type="checkbox"
                        className="h-4 w-4"
                        checked={selectedIds.includes(inv.id)}
                        onChange={() => toggleSelectInvestor(inv.id)}
                      />
                      <span>
                        {inv.name || "—"}{" "}
                        <span className="text-gray-500">
                          ({inv.email || "—"})
                        </span>
                      </span>
                    </label>
                  ))
                )}
              </div>

              <div className="flex items-center justify-end gap-2 border-t px-4 py-3">
                <button
                  type="button"
                  onClick={closeAddModal}
                  className="inline-flex items-center rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving || selectedIds.length === 0}
                  className="inline-flex items-center rounded-md bg-blue-600 px-4 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
                >
                  {saving ? "Saving..." : "Add Selected"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Add Group Investor Admin Modal */}
      {isAddAdminModalOpen && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30">
          <div className="bg-white rounded-lg shadow-lg w-full max-w-md">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <h3 className="text-sm font-semibold">Add Group Investor Admin</h3>
              <button
                type="button"
                onClick={closeAddAdminModal}
                className="text-gray-400 hover:text-gray-600"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateGroupAdmin}>
              <div className="px-4 py-3 space-y-3">
                <p className="text-xs text-gray-500">
                  Select an investor user to promote to Group Investor Admin.
                </p>

                {loadingInvestorUsers ? (
                  <div className="text-sm text-gray-500">
                    Loading investors...
                  </div>
                ) : investorUsers.length === 0 ? (
                  <div className="text-sm text-gray-500">
                    No eligible investors found.
                  </div>
                ) : (
                  <select
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                    value={selectedAdminUserId}
                    onChange={(e) => setSelectedAdminUserId(e.target.value)}
                  >
                    <option value="">Select an investor</option>
                    {investorUsers.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name} ({u.email})
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <div className="flex items-center justify-end gap-2 border-t px-4 py-3">
                <button
                  type="button"
                  onClick={closeAddAdminModal}
                  className="inline-flex items-center rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={
                    savingAdmin ||
                    !selectedAdminUserId ||
                    investorUsers.length === 0
                  }
                  className="inline-flex items-center rounded-md bg-blue-600 px-4 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
                >
                  {savingAdmin ? "Saving..." : "Save as Group Admin"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
