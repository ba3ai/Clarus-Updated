// frontend/src/components/tabs/GroupInvestorAdmin.jsx
import React, { useEffect, useState } from "react";
import {
  Plus,
  X,
  Edit2,
  Trash2,
  UserPlus,
  ChevronRight,
  ChevronDown,
} from "lucide-react";

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

  // expanded row (clicking the arrow)
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

  // Edit Group Admin settings dialog
  const [isEditAdminModalOpen, setIsEditAdminModalOpen] = useState(false);
  const [editAdmin, setEditAdmin] = useState(null);
  const [editStatus, setEditStatus] = useState("");
  const [editPermission, setEditPermission] = useState("");

  // ---- NEW: edit-members checkbox list state ----
  const [editInvestors, setEditInvestors] = useState([]); // [{id,name,email}]
  const [editSelectedIds, setEditSelectedIds] = useState([]); // current checked
  const [editInitialMemberIds, setEditInitialMemberIds] = useState([]); // original members
  const [editLoadingInvestors, setEditLoadingInvestors] = useState(false);

  // Confirm dialogs
  const [confirmDeleteAdmin, setConfirmDeleteAdmin] = useState(null);
  const [confirmRemoveMember, setConfirmRemoveMember] = useState(null);

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
  // Remove investor from group (used by "Remove" in expanded table)
  // ---------------------------------------------------------------------------
  const handleRemoveMember = async (adminId, investorId) => {
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
  // Edit Group Admin modal (status/permission + member checkboxes)
  // ---------------------------------------------------------------------------
  const loadInvestorsForEdit = async (adminId) => {
    setEditLoadingInvestors(true);
    setError("");
    try {
      // current members
      const [mRes, aRes] = await Promise.all([
        xsrfFetch(`/api/admin/group-admins/${adminId}/investors`, {
          method: "GET",
        }),
        xsrfFetch(
          `/api/admin/group-admins/${adminId}/available-investors`,
          { method: "GET" }
        ),
      ]);

      const mData = await mRes.json().catch(() => ({}));
      const aData = await aRes.json().catch(() => ({}));

      if (!mRes.ok || mData.ok === false) {
        throw new Error(
          mData.message || `Failed to load members (${mRes.status})`
        );
      }
      if (!aRes.ok || aData.ok === false) {
        throw new Error(
          aData.message ||
            `Failed to load available investors (${aRes.status})`
        );
      }

      const members = mData.members || [];
      const available = aData.investors || [];

      const combined = [
        ...members.map((m) => ({
          id: m.investor_id,
          name: m.name,
          email: m.email,
          isMember: true,
        })),
        ...available.map((inv) => ({
          id: inv.id,
          name: inv.name,
          email: inv.email,
          isMember: false,
        })),
      ];

      const memberIds = members.map((m) => m.investor_id);

      setEditInvestors(combined);
      setEditSelectedIds(memberIds);
      setEditInitialMemberIds(memberIds);

      // also keep members cache up to date for expanded table
      setMembersByAdmin((prev) => ({
        ...prev,
        [adminId]: members,
      }));
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to load investors for editing");
    } finally {
      setEditLoadingInvestors(false);
    }
  };

  const openEditAdminModal = (admin) => {
    setEditAdmin(admin);
    setEditStatus(admin.status || "");
    setEditPermission(admin.permission || "");
    setIsEditAdminModalOpen(true);
    setEditInvestors([]);
    setEditSelectedIds([]);
    setEditInitialMemberIds([]);
    loadInvestorsForEdit(admin.id);
  };

  const closeEditAdminModal = () => {
    setIsEditAdminModalOpen(false);
    setEditAdmin(null);
    setEditStatus("");
    setEditPermission("");
    setEditInvestors([]);
    setEditSelectedIds([]);
    setEditInitialMemberIds([]);
  };

  const toggleEditInvestor = (id) => {
    setEditSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleSaveEditAdmin = async (e) => {
    e.preventDefault();
    if (!editAdmin) return;

    setSavingAdmin(true);
    setError("");

    try {
      // 1) Update status / permission
      const res = await xsrfFetch(
        `/api/admin/group-investor-admin/${editAdmin.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            status: editStatus,
            permission: editPermission,
          }),
        }
      );

      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(
          data.message ||
            `Failed to update Group Investor Admin (status ${res.status})`
        );
      }

      const updatedUser = data.user || {};
      setGroupAdmins((prev) =>
        prev.map((ga) =>
          ga.id === updatedUser.id ? { ...ga, ...updatedUser } : ga
        )
      );

      // 2) Diff membership checkboxes → add / remove investors
      const toAdd = editSelectedIds.filter(
        (id) => !editInitialMemberIds.includes(id)
      );
      const toRemove = editInitialMemberIds.filter(
        (id) => !editSelectedIds.includes(id)
      );

      if (toAdd.length) {
        const addRes = await xsrfFetch(
          `/api/admin/group-admins/${editAdmin.id}/investors`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ investor_ids: toAdd }),
          }
        );
        const addData = await addRes.json().catch(() => ({}));
        if (!addRes.ok || addData.ok === false) {
          throw new Error(
            addData.message ||
              `Failed to add investors to group (status ${addRes.status})`
          );
        }
      }

      if (toRemove.length) {
        // remove one by one
        for (const invId of toRemove) {
          const delRes = await xsrfFetch(
            `/api/admin/group-admins/${editAdmin.id}/investors/${invId}`,
            { method: "DELETE" }
          );
          const delData = await delRes.json().catch(() => ({}));
          if (!delRes.ok || delData.ok === false) {
            throw new Error(
              delData.message ||
                `Failed to remove investor from group (status ${delRes.status})`
            );
          }
        }
      }

      // refresh members list for expanded row
      await fetchMembersForAdmin(editAdmin.id);

      closeEditAdminModal();
    } catch (err) {
      console.error(err);
      setError(err.message || "Failed to update Group Investor Admin");
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

      <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-4 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-800">
              Group Investor Admins
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Click the arrow on the left to view investors in each group.
            </p>
          </div>
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
          <div className="overflow-x-auto rounded-lg border border-gray-100">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-xs font-semibold uppercase text-gray-500">
                  <th className="w-10 px-3 py-2" />
                  <th className="px-3 py-2 text-left">Name</th>
                  <th className="px-3 py-2 text-left">Email</th>
                  <th className="px-3 py-2 text-left">Created</th>
                  <th className="px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {groupAdmins.map((admin, idx) => {
                  const members = membersByAdmin[admin.id] || [];
                  const isExpanded = expandedAdminId === admin.id;
                  const rowBg = idx % 2 === 0 ? "bg-white" : "bg-gray-50";

                  return (
                    <React.Fragment key={admin.id}>
                      <tr className={`${rowBg} border-b border-gray-100`}>
                        {/* expand arrow */}
                        <td className="px-3 py-2 align-top">
                          <button
                            type="button"
                            onClick={() => toggleExpandAdmin(admin.id)}
                            className="inline-flex h-7 w-7 items-center justify-center rounded hover:bg-gray-100 text-gray-500"
                            aria-label={
                              isExpanded
                                ? "Collapse investors list"
                                : "Expand to see investors"
                            }
                          >
                            {isExpanded ? (
                              <ChevronDown size={16} />
                            ) : (
                              <ChevronRight size={16} />
                            )}
                          </button>
                        </td>

                        {/* admin name */}
                        <td className="px-3 py-2 whitespace-nowrap align-middle">
                          <div className="flex flex-col">
                            <span className="font-medium text-gray-900">
                              {admin.name || "—"}
                            </span>
                            {members.length > 0 && (
                              <span className="mt-0.5 inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
                                {members.length} investor
                                {members.length !== 1 ? "s" : ""}
                              </span>
                            )}
                          </div>
                        </td>

                        {/* email */}
                        <td className="px-3 py-2 whitespace-nowrap text-gray-700 align-middle">
                          {admin.email || "—"}
                        </td>

                        {/* created */}
                        <td className="px-3 py-2 whitespace-nowrap text-gray-500 text-xs align-middle">
                          {admin.created_at
                            ? new Date(admin.created_at).toLocaleDateString()
                            : "—"}
                        </td>

                        {/* actions */}
                        <td className="px-3 py-2 whitespace-nowrap align-middle">
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
                              onClick={() => openEditAdminModal(admin)}
                              className="inline-flex items-center gap-1 rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
                            >
                              <Edit2 size={14} />
                              Edit
                            </button>

                            <button
                              type="button"
                              onClick={() => setConfirmDeleteAdmin(admin)}
                              className="inline-flex items-center gap-1 rounded-md border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                            >
                              <Trash2 size={14} />
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>

                      {/* expanded investors row */}
                      {isExpanded && (
                        <tr className="bg-gray-50 border-b border-gray-100">
                          <td className="px-3 py-3" />
                          <td
                            className="px-3 py-3 text-sm text-gray-700"
                            colSpan={4}
                          >
                            <div className="flex items-center justify-between mb-2">
                              <div className="font-semibold">
                                Investors in this group
                              </div>
                              <span className="text-xs text-gray-500">
                                {members.length}{" "}
                                {members.length === 1
                                  ? "investor"
                                  : "investors"}
                              </span>
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
                              <div className="rounded-md border border-gray-200 bg-white">
                                <table className="min-w-full text-xs">
                                  <thead className="bg-gray-50 text-gray-500 uppercase">
                                    <tr>
                                      <th className="px-3 py-1 text-left">
                                        Investor
                                      </th>
                                      <th className="px-3 py-1 text-left">
                                        Email
                                      </th>
                                      <th className="px-3 py-1 text-right">
                                        Actions
                                      </th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {members.map((m) => (
                                      <tr
                                        key={m.investor_id}
                                        className="border-t border-gray-100"
                                      >
                                        <td className="px-3 py-1.5">
                                          {m.name || "—"}
                                        </td>
                                        <td className="px-3 py-1.5 text-gray-600">
                                          {m.email || "—"}
                                        </td>
                                        <td className="px-3 py-1.5 text-right">
                                          <button
                                            type="button"
                                            onClick={() =>
                                              setConfirmRemoveMember({
                                                admin,
                                                member: m,
                                              })
                                            }
                                            className="text-xs text-red-600 hover:text-red-800"
                                          >
                                            Remove
                                          </button>
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
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

      {/* Edit Group Investor Admin Modal (with member checkboxes) */}
      {isEditAdminModalOpen && editAdmin && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30">
          <div className="bg-white rounded-lg shadow-lg w-full max-w-lg">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <h3 className="text-sm font-semibold">
                Edit Group Investor Admin
              </h3>
              <button
                type="button"
                onClick={closeEditAdminModal}
                className="text-gray-400 hover:text-gray-600"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSaveEditAdmin}>
              <div className="px-4 py-3 space-y-4 text-sm">
                <div>
                  <div className="text-xs font-medium text-gray-500 mb-1">
                    Name
                  </div>
                  <div className="text-gray-800">
                    {editAdmin.name || "—"}
                  </div>
                </div>

                <div>
                  <div className="text-xs font-medium text-gray-500 mb-1">
                    Email
                  </div>
                  <div className="text-gray-800">
                    {editAdmin.email || "—"}
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Status
                    </label>
                    <input
                      type="text"
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                      value={editStatus}
                      onChange={(e) => setEditStatus(e.target.value)}
                      placeholder="e.g. Active, Inactive"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Permission
                    </label>
                    <input
                      type="text"
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                      value={editPermission}
                      onChange={(e) => setEditPermission(e.target.value)}
                      placeholder="e.g. Viewer, Editor, Owner"
                    />
                  </div>
                </div>

                {/* NEW: member checkbox list */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium text-gray-600">
                      Group investors
                    </span>
                    <span className="text-[11px] text-gray-500">
                      Checked investors belong to this group.
                    </span>
                  </div>

                  {editLoadingInvestors ? (
                    <div className="text-sm text-gray-500">
                      Loading investors...
                    </div>
                  ) : editInvestors.length === 0 ? (
                    <div className="text-sm text-gray-500">
                      No eligible investors found.
                    </div>
                  ) : (
                    <div className="max-h-64 overflow-y-auto space-y-1 mt-1">
                      {editInvestors.map((inv) => (
                        <label
                          key={inv.id}
                          className="flex items-center gap-2 rounded-md border border-gray-200 px-3 py-1.5 text-sm hover:bg-gray-50"
                        >
                          <input
                            type="checkbox"
                            className="h-4 w-4"
                            checked={editSelectedIds.includes(inv.id)}
                            onChange={() => toggleEditInvestor(inv.id)}
                          />
                          <span>
                            {inv.name || "—"}{" "}
                            <span className="text-gray-500">
                              ({inv.email || "—"})
                            </span>
                            {editInitialMemberIds.includes(inv.id) && (
                              <span className="ml-1 text-[10px] text-green-600">
                                current
                              </span>
                            )}
                          </span>
                        </label>
                      ))}
                    </div>
                  )}

                  <p className="mt-1 text-[11px] text-gray-500">
                    Unchecking an investor will remove them from this group when
                    you save.
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 border-t px-4 py-3">
                <button
                  type="button"
                  onClick={closeEditAdminModal}
                  className="inline-flex items-center rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingAdmin}
                  className="inline-flex items-center rounded-md bg-blue-600 px-4 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
                >
                  {savingAdmin ? "Saving..." : "Save changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Confirm Delete Group Admin Modal */}
      {confirmDeleteAdmin && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30">
          <div className="bg-white rounded-lg shadow-lg w-full max-w-sm">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <h3 className="text-sm font-semibold">Delete Group Admin</h3>
              <button
                type="button"
                onClick={() => setConfirmDeleteAdmin(null)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X size={18} />
              </button>
            </div>
            <div className="px-4 py-3 text-sm text-gray-700 space-y-2">
              <p>Are you sure you want to delete this Group Investor Admin?</p>
              <p className="font-medium">
                {confirmDeleteAdmin.name || confirmDeleteAdmin.email}
              </p>
              <p className="text-xs text-gray-500">
                This will demote them back to a regular investor and remove
                their group memberships.
              </p>
            </div>
            <div className="flex items-center justify-end gap-2 border-t px-4 py-3">
              <button
                type="button"
                onClick={() => setConfirmDeleteAdmin(null)}
                className="inline-flex items-center rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={async () => {
                  const adminId = confirmDeleteAdmin.id;
                  await handleDeleteAdmin(adminId);
                  setConfirmDeleteAdmin(null);
                }}
                className="inline-flex items-center rounded-md bg-red-600 px-4 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-red-700"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Remove Member Modal (from expanded table) */}
      {confirmRemoveMember && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30">
          <div className="bg-white rounded-lg shadow-lg w-full max-w-sm">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <h3 className="text-sm font-semibold">Remove Investor</h3>
              <button
                type="button"
                onClick={() => setConfirmRemoveMember(null)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X size={18} />
              </button>
            </div>
            <div className="px-4 py-3 text-sm text-gray-700 space-y-2">
              <p>Remove this investor from the group?</p>
              <p className="font-medium">
                {confirmRemoveMember.member.name} (
                {confirmRemoveMember.member.email || "—"})
              </p>
            </div>
            <div className="flex items-center justify-end gap-2 border-t px-4 py-3">
              <button
                type="button"
                onClick={() => setConfirmRemoveMember(null)}
                className="inline-flex items-center rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={async () => {
                  const adminId = confirmRemoveMember.admin.id;
                  const investorId = confirmRemoveMember.member.investor_id;
                  await handleRemoveMember(adminId, investorId);
                  setConfirmRemoveMember(null);
                }}
                className="inline-flex items-center rounded-md bg-red-600 px-4 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-red-700"
              >
                Remove
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
