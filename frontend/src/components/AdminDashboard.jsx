// frontend/src/components/AdminDashboard.jsx
import React, {
  useState,
  useContext,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { AuthContext } from "../context/AuthContext";
import api from "../services/api";

import {
  Home,
  UserPlus,
  Users,
  FileSpreadsheet,
  FileText,
  Keyboard,
  LogOut,
  BarChart2,
  Bell,
  Check,
  X,
  Loader2,
  Mail,
} from "lucide-react";

import Settings from "./tabs/Settings";
import AddUser from "./tabs/AddUser";
import AllUsers from "./tabs/AllUsers";
import ExcelSheet from "./tabs/ExcelSheet";
import QuickBooks from "./tabs/QuickBooks";
import ManualEntry from "./tabs/ManualEntry";
import Overview from "./tabs/Overview";
import Investors from "./tabs/Investors";
import Documents from "./tabs/Documents";
import KnowledgeBase from "./tabs/KnowledgeBase";
import GroupInvestorAdmin from "./tabs/GroupInvestorAdmin";

const AdminDashboard = () => {
  const [activeTab, setActiveTab] = useState("overview");
  const { user, logout } = useContext(AuthContext);

  if (user === undefined) return <div className="p-6">Loading…</div>;

  const adminData = {
    fullName:
      user?.name ||
      [user?.first_name, user?.last_name].filter(Boolean).join(" ") ||
      "Admin",
    email: user?.email || "",
    userType: (user?.user_type || "").toLowerCase(),
  };

  const SectionCard = ({ title, children }) => (
    <div className="space-y-4">
      <div className="bg-white border rounded-xl shadow-sm">
        <div className="px-4 py-3 border-b">
          <h3 className="text-base font-semibold text-gray-800">{title}</h3>
        </div>
        <div className="p-4 text-sm text-gray-600">{children}</div>
      </div>
    </div>
  );

  const renderTab = () => {
    switch (activeTab) {
      case "overview":
        return <Overview />;
      case "investors":
        return <Investors />;
      case "groupInvestorAdmin":
        return <GroupInvestorAdmin />;
      case "companies":
        return (
          <SectionCard title="Companies">
            Portfolio companies with metrics, documents, and valuations.
            (Placeholder UI)
          </SectionCard>
        );
      case "management":
        return (
          <SectionCard title="Management">
            Management company items: fees, expenses, approvals, workflows.
            (Placeholder UI)
          </SectionCard>
        );
      case "documents":
        return <Documents />;
      case "settings":
        return <Settings />;
      case "addUser":
        return <AddUser />;
      case "allUsers":
        return <AllUsers />;
      case "excel":
        return <ExcelSheet />;
      case "quickbooks":
        return <QuickBooks />;
      case "manual":
        return <ManualEntry />;
      case "knowledge":
        return <KnowledgeBase />;
      default:
        return <Overview />;
    }
  };

  const TabButton = ({ label, tabKey, icon }) => (
    <button
      onClick={() => setActiveTab(tabKey)}
      className={`flex items-center gap-2 w-full px-4 py-2 rounded-md text-sm transition font-medium ${
        activeTab === tabKey
          ? "bg-blue-100 text-blue-800"
          : "text-gray-700 hover:bg-gray-200"
      }`}
    >
      {icon}
      {label}
    </button>
  );

  // ------------------- Notifications -------------------
  const [notifOpen, setNotifOpen] = useState(false);
  // invites | deletes | dependents | groups
  const [notifTab, setNotifTab] = useState("invites");
  const [counts, setCounts] = useState({
    invites: 0,
    deletes: 0,
    dependents: 0,
    groups: 0,
  });
  const [loadingCounts, setLoadingCounts] = useState(false);

  const [pendingInvites, setPendingInvites] = useState([]);
  const [loadingInvites, setLoadingInvites] = useState(false);

  const [deleteReqs, setDeleteReqs] = useState([]);
  const [loadingDeletes, setLoadingDeletes] = useState(false);

  const [dependentReqs, setDependentReqs] = useState([]);
  const [loadingDependents, setLoadingDependents] = useState(false);

  const [groupReqs, setGroupReqs] = useState([]);
  const [loadingGroups, setLoadingGroups] = useState(false);

  const notifRef = useRef(null);

  const sumBadge = useMemo(
    () =>
      Number(counts.invites || 0) +
      Number(counts.deletes || 0) +
      Number(counts.dependents || 0) +
      Number(counts.groups || 0),
    [counts]
  );

  const fmtDT = (v) => {
    if (!v) return "—";
    const d = new Date(v);
    return Number.isNaN(d.getTime()) ? v : d.toLocaleString();
  };

  // --- API helpers ---

  const refreshCounts = async () => {
    setLoadingCounts(true);
    try {
      let invites = 0;
      let deletes = 0;
      let dependents = 0;
      let groups = 0;

      try {
        const { data } = await api.get("/api/invitations/stats");
        invites = Number(data?.pending || 0);
      } catch (err) {
        console.error("Error loading invite stats", err);
      }

      try {
        const { data } = await api.get("/api/deletion-requests/stats");
        deletes = Number(data?.pending || 0);
      } catch (err) {
        console.error("Error loading delete stats", err);
      }

      try {
        const { data } = await api.get(
          "/api/notifications/admin/dependent-requests/unread-count"
        );
        dependents = Number(data?.count || 0);
      } catch (err) {
        console.error("Error loading dependent stats", err);
      }

      try {
        const { data } = await api.get(
          "/api/notifications/admin/group-requests/unread-count"
        );
        groups = Number(data?.count || 0);
      } catch (err) {
        console.error("Error loading group-request stats", err);
      }

      setCounts({ invites, deletes, dependents, groups });
    } finally {
      setLoadingCounts(false);
    }
  };

  const loadPendingInvites = async () => {
    setLoadingInvites(true);
    try {
      const { data } = await api.get("/api/invitations", {
        params: {
          status: "pending",
          per_page: 100,
          page: 1,
          sort: "created_at",
          order: "desc",
        },
      });
      const list = Array.isArray(data) ? data : data?.items || [];
      setPendingInvites(list);
    } catch (err) {
      console.error("Error loading pending invites", err);
    } finally {
      setLoadingInvites(false);
    }
  };

  const loadDeleteRequests = async () => {
    setLoadingDeletes(true);
    try {
      const { data } = await api.get("/api/deletion-requests");
      const list = Array.isArray(data) ? data : [];
      setDeleteReqs(list);
    } catch (err) {
      console.error("Error loading delete requests", err);
    } finally {
      setLoadingDeletes(false);
    }
  };

  const loadDependentRequests = async () => {
    setLoadingDependents(true);
    try {
      const { data } = await api.get(
        "/api/notifications/admin/dependent-requests"
      );
      const list = Array.isArray(data) ? data : [];
      setDependentReqs(list);
    } catch (err) {
      console.error("Error loading dependent requests", err);
    } finally {
      setLoadingDependents(false);
    }
  };

  const loadGroupRequests = async () => {
    setLoadingGroups(true);
    try {
      const { data } = await api.get(
        "/api/notifications/admin/group-requests"
      );
      const list = Array.isArray(data) ? data : [];
      setGroupReqs(list);
    } catch (err) {
      console.error("Error loading group requests", err);
    } finally {
      setLoadingGroups(false);
    }
  };

  useEffect(() => {
    refreshCounts();
    const id = setInterval(refreshCounts, 60_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    function onDoc(e) {
      if (!notifRef.current) return;
      if (!notifRef.current.contains(e.target)) setNotifOpen(false);
    }
    if (notifOpen) document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [notifOpen]);

  const openNotifications = async () => {
    setNotifOpen((v) => !v);
    if (!notifOpen) {
      await Promise.all([
        loadPendingInvites(),
        loadDeleteRequests(),
        loadDependentRequests(),
        loadGroupRequests(),
        refreshCounts(),
      ]);
    }
  };

  // actions
  const cancelInvite = async (id) => {
    if (!window.confirm("Cancel this invitation?")) return;
    try {
      await api.delete(`/api/invitations/${id}`);
      await Promise.all([loadPendingInvites(), refreshCounts()]);
      // optional: close dropdown after cancelling invite
      // setNotifOpen(false);
    } catch (e) {
      alert(e?.response?.data?.error || e?.message || "Cancel failed.");
    }
  };

  // merged from 2nd dev: approve dependent investor invite
  const approveInvite = async (id) => {
    try {
      await api.post(`/api/invitations/${id}/approve-dependent`);
      await Promise.all([loadPendingInvites(), refreshCounts()]);
    } catch (e) {
      alert(e?.response?.data?.error || e?.message || "Approve failed.");
    }
  };

  const approveDelete = async (id) => {
    try {
      await api.post(`/api/deletion-requests/${id}/approve`);
    } catch (e) {
      alert(e?.response?.data?.error || e?.message || "Approve failed.");
    } finally {
      await Promise.all([loadDeleteRequests(), refreshCounts()]);
    }
  };

  const rejectDelete = async (id) => {
    try {
      await api.post(`/api/deletion-requests/${id}/reject`);
    } catch (e) {
      alert(e?.response?.data?.error || e?.message || "Reject failed.");
    } finally {
      await Promise.all([loadDeleteRequests(), refreshCounts()]);
    }
  };

  // ---------- Dependent request helpers & actions ----------

  const parseDependentNameEmail = (msg = "") => {
    const text = msg.replace(/<[^>]+>/g, " ");
    const m = text.match(/for\s+(.+?)\s*\(([^()]+@[^()]+)\)/i);
    if (!m) return { name: "", email: "" };
    return {
      name: m[1].trim(),
      email: m[2].trim().toLowerCase(),
    };
  };

  const hasExistingAccount = (msg = "") =>
    msg.toLowerCase().includes("existing account detected");

  const approveDependentRequest = async (notif) => {
    if (!window.confirm("Mark this dependent account request as approved?")) {
      return;
    }
    try {
      await api.post(
        "/api/notifications/admin/dependent-requests/mark-read",
        { ids: [notif.id] }
      );
      await Promise.all([loadDependentRequests(), refreshCounts()]);
      // close notifications dropdown after approval
      setNotifOpen(false);
    } catch (e) {
      alert(
        e?.response?.data?.error ||
          e?.message ||
          "Failed to approve dependent request."
      );
    }
  };

  const sendInviteForDependent = async (notif) => {
    const { name, email } = parseDependentNameEmail(notif.message || "");
    if (!email) {
      alert("Could not detect an email address in this request.");
      return;
    }

    if (!window.confirm(`Send invitation to ${name || email}? (${email})`)) {
      return;
    }

    try {
      const res = await api.post("/api/invitations", {
        name: name || email,
        email,
        user_type: "Investor",
      });

      await api.post(
        "/api/notifications/admin/dependent-requests/mark-read",
        { ids: [notif.id] }
      );

      await Promise.all([
        loadPendingInvites(),
        loadDependentRequests(),
        refreshCounts(),
      ]);

      const msg = res?.data?.msg;
      alert(
        msg === "resent"
          ? "Invitation resent to this email."
          : "Invitation sent."
      );

      // close notifications dropdown after sending invite
      setNotifOpen(false);
    } catch (e) {
      alert(
        e?.response?.data?.error ||
          e?.message ||
          "Failed to send invitation."
      );
    }
  };

  const dismissDependentRequest = async (notif) => {
    try {
      await api.post(
        "/api/notifications/admin/dependent-requests/mark-read",
        { ids: [notif.id] }
      );
      await Promise.all([loadDependentRequests(), refreshCounts()]);
      // close notifications dropdown after dismiss
      setNotifOpen(false);
    } catch (e) {
      alert(
        e?.response?.data?.error ||
          e?.message ||
          "Failed to dismiss notification."
      );
    }
  };

  // ---------- Group request helpers & actions ----------

  const parseGroupRequest = (msg = "") => {
    const text = msg.replace(/\r/g, "");
    const lines = text.split("\n").map((l) => l.trim());
    let requester = "";
    const members = [];

    lines.forEach((line) => {
      if (!line) return;
      const reqMatch = line.match(/^Group account request from (.+)\.?$/i);
      if (reqMatch) {
        requester = reqMatch[1].trim();
        return;
      }
      const memMatch = line.match(/^[-•]\s*(.+?)\s*<([^>]+)>/);
      if (memMatch) {
        members.push({
          name: memMatch[1].trim(),
          email: memMatch[2].trim().toLowerCase(),
        });
      }
    });

    return { requester, members };
  };

  const dismissGroupRequest = async (notif) => {
    try {
      await api.post(
        "/api/notifications/admin/group-requests/mark-read",
        { ids: [notif.id] }
      );
      await Promise.all([loadGroupRequests(), refreshCounts()]);
      setNotifOpen(false);
    } catch (e) {
      alert(
        e?.response?.data?.error ||
          e?.message ||
          "Failed to dismiss group request."
      );
    }
  };

  const approveGroupMember = async (notif, member) => {
    if (
      !window.confirm(
        `Mark ${member.name || member.email} as approved for this group request?`
      )
    ) {
      return;
    }

    try {
      // backend should promote requester to group_admin (if needed)
      // and attach this member (by email) into the InvestorGroupMembership table.
      await api.post("/api/admin/group-requests/approve", {
        notification_id: notif.id,
        member_email: member.email,
      });

      await Promise.all([loadGroupRequests(), refreshCounts()]);
      setNotifOpen(false);
    } catch (e) {
      alert(
        e?.response?.data?.message ||
          e?.response?.data?.error ||
          e?.message ||
          "Failed to approve group request."
      );
    }
  };

  const sendInviteForGroupMember = async (notif, member) => {
    if (!member.email) {
      alert("Could not detect an email address for this member.");
      return;
    }

    if (
      !window.confirm(
        `Send invitation to ${member.name || member.email}? (${member.email})`
      )
    ) {
      return;
    }

    try {
      const res = await api.post("/api/invitations", {
        name: member.name || member.email,
        email: member.email,
        user_type: "Investor",
      });

      await api.post(
        "/api/notifications/admin/group-requests/mark-read",
        { ids: [notif.id] }
      );

      await Promise.all([
        loadPendingInvites(),
        loadGroupRequests(),
        refreshCounts(),
      ]);

      const msg = res?.data?.msg;
      alert(
        msg === "resent"
          ? "Invitation resent to this email."
          : "Invitation sent."
      );
      setNotifOpen(false);
    } catch (e) {
      alert(
        e?.response?.data?.error ||
          e?.message ||
          "Failed to send invitation."
      );
    }
  };

  // ------------------- UI -------------------
  return (
    <div className="flex min-h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="w-64 bg-gray-100 border-r border-gray-200 flex flex-col justify-between shadow-sm">
        <div>
          <div className="px-6 py-5 border-b border-gray-200">
            <h2
              className="text-xl font-bold text-center tracking-tight cursor-pointer hover:text-blue-600"
              onClick={() => setActiveTab("overview")}
            >
              Admin Panel
            </h2>
            <p className="text-lg text-black-600 text-center">
              Financial Reporting Agent
            </p>
          </div>

          <nav className="p-4 space-y-6 ml-[10px]">
            <div>
              <h3 className="text-base font-bold text-gray-500 uppercase mb-2">
                Dashboard
              </h3>
              <TabButton
                label="Overview"
                tabKey="overview"
                icon={<Home size={16} />}
              />
              <TabButton
                label="Investors"
                tabKey="investors"
                icon={<Users size={16} />}
              />
              <TabButton
                label="Group Investor Admin"
                tabKey="groupInvestorAdmin"
                icon={<Users size={16} />}
              />
              <TabButton
                label="Documents"
                tabKey="documents"
                icon={<FileText size={16} />}
              />
              <TabButton
                label="Settings"
                tabKey="settings"
                icon={<Home size={16} />}
              />
            </div>

            <div>
              <h3 className="text-base font-bold text-gray-500 uppercase mb-2">
                Users
              </h3>
              <TabButton
                label="Add User"
                tabKey="addUser"
                icon={<UserPlus size={16} />}
              />
              <TabButton
                label="All Users"
                tabKey="allUsers"
                icon={<Users size={16} />}
              />
            </div>

            <div>
              <h3 className="text-base font-bold text-gray-500 uppercase mb-2">
                Integration
              </h3>
              <TabButton
                label="Excel Sheet"
                tabKey="excel"
                icon={<FileSpreadsheet size={16} />}
              />
              <TabButton
                label="QuickBooks"
                tabKey="quickbooks"
                icon={<FileText size={16} />}
              />
            </div>

            <div>
              <h3 className="text-base font-bold text-gray-500 uppercase mb-2">
                Manual Entry
              </h3>
              <TabButton
                label="Entry Form"
                tabKey="manual"
                icon={<Keyboard size={16} />}
              />
            </div>

            <div>
              <h3 className="text-base font-bold text-gray-500 uppercase mb-2">
                Funds
              </h3>
              <a
                href="/admin/opportunity"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 w-full px-4 py-2 rounded-md text-sm transition font-medium text-gray-700 hover:bg-gray-200"
              >
                <FileText size={16} />
                Opportunity Fund
              </a>
              <a
                href="/admin/generalpartner"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 w-full px-4 py-2 rounded-md text-sm transition font-medium text-gray-700 hover:bg-gray-200"
              >
                <BarChart2 size={16} />
                General Partner
              </a>
            </div>
          </nav>
        </div>

        <div className="p-4 border-t border-gray-200">
          <button
            onClick={logout}
            className="flex items-center gap-2 text-red-500 hover:text-red-700 transition w-full text-sm font-medium"
          >
            <LogOut size={16} />
            Logout
          </button>
          <p className="text-xs mt-2 text-gray-400">Logged in as Admin</p>
        </div>
      </aside>

      {/* Main Area */}
      <div className="flex-1 flex flex-col">
        <header className="flex justify-end items-center gap-4 p-4 bg-white border-b relative">
          <div className="relative" ref={notifRef}>
            <button
              type="button"
              onClick={openNotifications}
              className="relative inline-flex items-center justify-center rounded-full h-10 w-10 border border-gray-200 bg-white hover:bg-gray-50"
              title="Notifications"
            >
              <Bell size={18} />
              <span className="sr-only">Notifications</span>
              {loadingCounts ? (
                <span className="absolute -top-1 -right-1 inline-flex items-center justify-center h-5 w-5 rounded-full bg-gray-300 text-[10px] text-white">
                  <Loader2 className="animate-spin" size={12} />
                </span>
              ) : sumBadge > 0 ? (
                <span className="absolute -top-1 -right-1 inline-flex items-center justify-center h-5 min-w-[20px] rounded-full bg-rose-600 text-[10px] text-white px-1">
                  {sumBadge}
                </span>
              ) : null}
            </button>

            {notifOpen && (
              <div className="absolute right-0 mt-2 w-[460px] bg-white border rounded-xl shadow-xl z-50">
                <div className="flex items-center justify-between border-b px-4 py-3">
                  <div className="font-semibold text-gray-800">
                    Notifications
                  </div>
                  <div className="text-xs text-gray-500">
                    {loadingCounts ? "Refreshing…" : "Up to date"}
                  </div>
                </div>

                <div className="px-4 pt-3">
                  <div className="flex flex-wrap gap-2">
                    <button
                      className={`px-3 py-1.5 rounded-md text-sm border ${
                        notifTab === "invites"
                          ? "bg-blue-600 text-white border-blue-600"
                          : "bg-white text-gray-700 border-gray-200 hover:bg-gray-50"
                      }`}
                      onClick={() => setNotifTab("invites")}
                    >
                      Invites{" "}
                      {counts.invites ? `(${counts.invites})` : ""}
                    </button>
                    <button
                      className={`px-3 py-1.5 rounded-md text-sm border ${
                        notifTab === "deletes"
                          ? "bg-blue-600 text-white border-blue-600"
                          : "bg-white text-gray-700 border-gray-200 hover:bg-gray-50"
                      }`}
                      onClick={() => setNotifTab("deletes")}
                    >
                      Delete Requests{" "}
                      {counts.deletes ? `(${counts.deletes})` : ""}
                    </button>
                    <button
                      className={`px-3 py-1.5 rounded-md text-sm border ${
                        notifTab === "dependents"
                          ? "bg-blue-600 text-white border-blue-600"
                          : "bg-white text-gray-700 border-gray-200 hover:bg-gray-50"
                      }`}
                      onClick={() => setNotifTab("dependents")}
                    >
                      Dependent Requests{" "}
                      {counts.dependents ? `(${counts.dependents})` : ""}
                    </button>
                    <button
                      className={`px-3 py-1.5 rounded-md text-sm border ${
                        notifTab === "groups"
                          ? "bg-blue-600 text-white border-blue-600"
                          : "bg-white text-gray-700 border-gray-200 hover:bg-gray-50"
                      }`}
                      onClick={() => setNotifTab("groups")}
                    >
                      Group Requests{" "}
                      {counts.groups ? `(${counts.groups})` : ""}
                    </button>
                  </div>
                </div>

                <div className="max-h-[60vh] overflow-y-auto px-4 py-3">
                  {notifTab === "invites" ? (
                    <>
                      {loadingInvites ? (
                        <div className="text-sm text-gray-500 p-3">
                          Loading pending invitations…
                        </div>
                      ) : pendingInvites.length === 0 ? (
                        <div className="text-sm text-gray-500 p-3">
                          No pending invitations.
                        </div>
                      ) : (
                        <ul className="space-y-2">
                          {pendingInvites.map((p) => {
                            const isDependent =
                              p.is_dependent_request ||
                              Boolean(p.invited_parent_investor_id);

                            return (
                              <li
                                key={p.id}
                                className="border rounded-lg p-3 flex items-center justify-between"
                              >
                                <div className="text-sm">
                                  <div className="font-medium text-gray-800">
                                    {p.name || p.email || "—"}
                                  </div>
                                  <div className="text-gray-500">
                                    {p.email} • invited{" "}
                                    {fmtDT(p.created_at)}
                                  </div>
                                  {isDependent && (
                                    <div className="text-xs text-blue-600 mt-1">
                                      Dependent investor request
                                    </div>
                                  )}
                                </div>
                                <div className="flex items-center gap-2">
                                  {isDependent && (
                                    <button
                                      onClick={() => approveInvite(p.id)}
                                      className="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 text-emerald-800 px-2 py-1 text-xs hover:bg-emerald-100"
                                      title="Approve dependent investor"
                                    >
                                      <Check size={14} />
                                      Accept
                                    </button>
                                  )}
                                  <button
                                    onClick={() => cancelInvite(p.id)}
                                    className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-gray-50"
                                    title="Cancel invitation"
                                  >
                                    <X size={14} />
                                    Cancel
                                  </button>
                                </div>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </>
                  ) : notifTab === "deletes" ? (
                    <>
                      {loadingDeletes ? (
                        <div className="text-sm text-gray-500 p-3">
                          Loading delete requests…
                        </div>
                      ) : deleteReqs.length === 0 ? (
                        <div className="text-sm text-gray-500 p-3">
                          No delete requests.
                        </div>
                      ) : (
                        <ul className="space-y-2">
                          {deleteReqs.map((r) => (
                            <li key={r.id} className="border rounded-lg p-3">
                              <div className="flex items-center justify-between">
                                <div className="text-sm">
                                  <div className="font-medium text-gray-800">
                                    Investor #{r.investor_id}
                                  </div>
                                  <div className="text-gray-500">
                                    Requested by #
                                    {r.requested_by_investor_id || "—"} •{" "}
                                    {fmtDT(r.created_at)}
                                  </div>
                                  {r.reason && (
                                    <div className="text-gray-600 mt-1">
                                      <span className="text-gray-500">
                                        Reason:
                                      </span>{" "}
                                      {r.reason}
                                    </div>
                                  )}
                                </div>
                                <div className="flex items-center gap-2">
                                  <button
                                    onClick={() => approveDelete(r.id)}
                                    className="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 text-emerald-800 px-2 py-1 text-xs hover:bg-emerald-100"
                                    title="Approve deletion"
                                  >
                                    <Check size={14} />
                                    Approve
                                  </button>
                                  <button
                                    onClick={() => rejectDelete(r.id)}
                                    className="inline-flex items-center gap-1 rounded-md border border-rose-200 bg-rose-50 text-rose-700 px-2 py-1 text-xs hover:bg-rose-100"
                                    title="Reject deletion"
                                  >
                                    <X size={14} />
                                    Reject
                                  </button>
                                </div>
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                    </>
                  ) : notifTab === "dependents" ? (
                    <>
                      {loadingDependents ? (
                        <div className="text-sm text-gray-500 p-3">
                          Loading dependent account requests…
                        </div>
                      ) : dependentReqs.length === 0 ? (
                        <div className="text-sm text-gray-500 p-3">
                          No dependent account requests.
                        </div>
                      ) : (
                        <ul className="space-y-2">
                          {dependentReqs.map((n) => {
                            const existing = hasExistingAccount(
                              n.message || ""
                            );
                            const { name, email } = parseDependentNameEmail(
                              n.message || ""
                            );
                            return (
                              <li
                                key={n.id}
                                className="border rounded-lg p-3 space-y-2"
                              >
                                <div className="flex items-start justify-between gap-3">
                                  <div className="text-sm">
                                    <div className="font-medium text-gray-800">
                                      {n.title ||
                                        "Dependent account request submitted"}
                                    </div>
                                    {n.message && (
                                      <div
                                        className="text-gray-700 mt-1 whitespace-pre-line"
                                        dangerouslySetInnerHTML={{
                                          __html: n.message,
                                        }}
                                      />
                                    )}
                                    <div className="text-xs text-gray-500 mt-1">
                                      {fmtDT(n.created_at)}
                                    </div>
                                    {email && (
                                      <div className="text-xs text-gray-500 mt-0.5">
                                        {name || "Dependent"} • {email}
                                      </div>
                                    )}
                                  </div>

                                  <button
                                    onClick={() =>
                                      dismissDependentRequest(n)
                                    }
                                    className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-gray-500 hover:bg-gray-50"
                                    title="Dismiss request"
                                  >
                                    <X size={14} />
                                  </button>
                                </div>

                                <div className="flex items-center gap-2">
                                  {existing ? (
                                    <button
                                      onClick={() =>
                                        approveDependentRequest(n)
                                      }
                                      className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-gray-50"
                                    >
                                      <Check size={14} />
                                      Approve request
                                    </button>
                                  ) : (
                                    <button
                                      onClick={() =>
                                        sendInviteForDependent(n)
                                      }
                                      className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-gray-50"
                                    >
                                      <Mail size={14} />
                                      Send invitation
                                    </button>
                                  )}
                                </div>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </>
                  ) : (
                    // Group Requests
                    <>
                      {loadingGroups ? (
                        <div className="text-sm text-gray-500 p-3">
                          Loading group account requests…
                        </div>
                      ) : groupReqs.length === 0 ? (
                        <div className="text-sm text-gray-500 p-3">
                          No group account requests.
                        </div>
                      ) : (
                        <ul className="space-y-2">
                          {groupReqs.map((n) => {
                            const { requester, members } = parseGroupRequest(
                              n.message || ""
                            );
                            return (
                              <li
                                key={n.id}
                                className="border rounded-lg p-3 space-y-2"
                              >
                                <div className="flex items-start justify-between gap-3">
                                  <div className="text-sm">
                                    <div className="font-medium text-gray-800">
                                      {n.title ||
                                        "Group account request submitted"}
                                    </div>
                                    {requester && (
                                      <div className="text-gray-700 mt-1">
                                        Request from:{" "}
                                        <span className="font-medium">
                                          {requester}
                                        </span>
                                      </div>
                                    )}
                                    <div className="text-xs text-gray-500 mt-1">
                                      {fmtDT(n.created_at)}
                                    </div>
                                  </div>

                                  <button
                                    onClick={() => dismissGroupRequest(n)}
                                    className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-gray-500 hover:bg-gray-50"
                                    title="Dismiss request"
                                  >
                                    <X size={14} />
                                  </button>
                                </div>

                                {members.length > 0 && (
                                  <div className="mt-2 space-y-2">
                                    {members.map((m) => (
                                      <div
                                        key={m.email}
                                        className="flex items-center justify-between gap-2 rounded-md bg-gray-50 px-2 py-1"
                                      >
                                        <div className="text-xs text-gray-700">
                                          <div className="font-medium">
                                            {m.name || "Group member"}
                                          </div>
                                          <div className="text-gray-500">
                                            {m.email}
                                          </div>
                                        </div>
                                        <div className="flex items-center gap-2">
                                          <button
                                            onClick={() =>
                                              approveGroupMember(n, m)
                                            }
                                            className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] hover:bg-gray-50"
                                          >
                                            <Check size={13} />
                                            Approve
                                          </button>
                                          <button
                                            onClick={() =>
                                              sendInviteForGroupMember(
                                                n,
                                                m
                                              )
                                            }
                                            className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] hover:bg-gray-50"
                                          >
                                            <Mail size={13} />
                                            Send invite
                                          </button>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </>
                  )}
                </div>

                <div className="border-t px-4 py-2 text-right">
                  <button
                    onClick={async () => {
                      await Promise.all([
                        loadPendingInvites(),
                        loadDeleteRequests(),
                        loadDependentRequests(),
                        loadGroupRequests(),
                        refreshCounts(),
                      ]);
                    }}
                    className="text-xs rounded-md border px-3 py-1 hover:bg-gray-50"
                  >
                    Refresh
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="relative group cursor-pointer">
            <div className="w-10 h-10 rounded-full bg-blue-600 text-white flex items-center justify-center text-lg font-bold">
              {adminData.fullName?.charAt(0).toUpperCase() || "A"}
            </div>
            <div className="absolute right-0 mt-2 hidden group-hover:block bg-white shadow-lg border rounded-md w-64 p-4 z-50">
              <h4 className="text-sm font-semibold text-gray-800 mb-2">
                Admin Info
              </h4>
              <div className="text-sm text-gray-600">
                <div>
                  <strong>Full Name:</strong> {adminData.fullName}
                </div>
                <div>
                  <strong>Email:</strong> {adminData.email}
                </div>
                <div>
                  <strong>User Type:</strong> {adminData.userType}
                </div>
              </div>
            </div>
          </div>
        </header>

        <main className="p-6 overflow-y-auto bg-white shadow-inner flex-1">
          {renderTab()}
        </main>
      </div>
    </div>
  );
};

export default AdminDashboard;
