import React, { useState, useEffect, useContext, useMemo } from "react";
import { AuthContext } from "../context/AuthContext";
import api from "../services/api";

import InvestorOverview from "./tabs/InvestorOverview";
import Portfolio from "./investments/Portfolio";
import Statements from "./investments/Statements";
import Documents from "./investments/Documents";
import PersonalInformation from "./investments/PersonalInformation";
import Accreditation from "./investments/Accreditation";
import Contacts from "./investments/Contacts";
import Settings from "./investments/Settings";

/* Icons */
const baseIconProps = {
  width: "1em",
  height: "1em",
  fill: "none",
  "aria-hidden": true,
};
const Icon = {
  menu: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" strokeWidth="2" />
    </svg>
  ),
  close: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <path d="M6 6l12 12M18 6l-12 12" stroke="currentColor" strokeWidth="2" />
    </svg>
  ),
  overview: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <path
        d="M3 12l9-7 9 7v7a2 2 0 01-2 2h-4a2 2 0 01-2-2v-3H9v3a2 2 0 01-2 2H3v-9z"
        stroke="currentColor"
        strokeWidth="2"
      />
    </svg>
  ),
  portfolio: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <path d="M3 7h18v10H3z" stroke="currentColor" strokeWidth="2" />
      <path
        d="M8 7V5a2 2 0 012-2h4a2 2 0 012 2v2"
        stroke="currentColor"
        strokeWidth="2"
      />
    </svg>
  ),
  statements: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <path d="M8 7h8M8 11h8M8 15h5" stroke="currentColor" strokeWidth="2" />
      <rect
        x="4"
        y="3"
        width="16"
        height="18"
        rx="2"
        stroke="currentColor"
        strokeWidth="2"
      />
    </svg>
  ),
  documents: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <path
        d="M14 3H6a2 2 0 00-2 2v14a2 2 0 002 2h8l6-6V5a2 2 0 00-2-2h-4z"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path d="M14 3v6h6" stroke="currentColor" strokeWidth="2" />
    </svg>
  ),
  person: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="2" />
      <path d="M6 20a6 6 0 0112 0" stroke="currentColor" strokeWidth="2" />
    </svg>
  ),
  badge: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <path
        d="M12 3l2.5 5 5.5.8-4 3.9.9 5.6L12 16l-4.9 2.3.9-5.6-4-3.9 5.5-.8L12 3z"
        stroke="currentColor"
        strokeWidth="2"
      />
    </svg>
  ),
  contacts: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <circle cx="8" cy="8" r="3" stroke="currentColor" strokeWidth="2" />
      <path d="M2 21a6 6 0 0112 0" stroke="currentColor" strokeWidth="2" />
      <rect
        x="14"
        y="7"
        width="8"
        height="10"
        rx="2"
        stroke="currentColor"
        strokeWidth="2"
      />
    </svg>
  ),
  group: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <path
        d="M16 11a4 4 0 10-8 0 4 4 0 008 0z"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path
        d="M3 21a7 7 0 0114 0M17 7a3 3 0 013-3 3 3 0 013 3M22 21a5 5 0 00-6-4"
        stroke="currentColor"
        strokeWidth="2"
      />
    </svg>
  ),
  settings: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <path
        d="M10.3 4.3a1 1 0 011.4 0l1.1 1.1a1 1 0 00.9.27l1.5-.34a1 1 0 011.16.58l.7 1.4a1 1 0 01-.18 1.11l-1.02 1.02a1 1 0 000 1.4l1.02 1.02a1 1 0 01.18 1.11l-.7 1.4a1 1 0 01-1.16.58l-1.5-.34a1 1 0 00-.9.27l-1.1 1.1a1 1 0 01-1.4 0l-1.1-1.1a1 1 0 00-.9-.27l-1.5.34a1 1 0 01-1.16-.58l-.7-1.4a1 1 0 01-.18-1.11L6.4 13.3a1 1 0 000-1.4L5.38 10.9a1 1 0 01-.18-1.11l.7-1.4a1 1 0 011.16-.58l1.5.34a1 1 0 00.9-.27l1.1-1.1z"
        stroke="currentColor"
        strokeWidth="2"
      />
      <circle cx="12" cy="12" r="2.5" stroke="currentColor" strokeWidth="2" />
    </svg>
  ),
  logout: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <path d="M15 17l5-5-5-5M20 12H9" stroke="currentColor" strokeWidth="2" />
      <path d="M4 4h6a2 2 0 012 2v2" stroke="currentColor" strokeWidth="2" />
      <path d="M12 16v2a2 2 0 01-2 2H4" stroke="currentColor" strokeWidth="2" />
    </svg>
  ),
  bell: () => (
    <svg viewBox="0 0 24 24" {...baseIconProps}>
      <path
        d="M12 3a4 4 0 00-4 4v2.1c0 .5-.2 1-.6 1.3L6 12.5V14h12v-1.5l-1.4-2.1a1.7 1.7 0 01-.6-1.3V7a4 4 0 00-4-4z"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path
        d="M10 18a2 2 0 004 0"
        stroke="currentColor"
        strokeWidth="2"
      />
    </svg>
  ),
};

const itemBase =
  "w-full text-left px-3 py-2 rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-sky-400 flex items-center gap-2 text-sm leading-5";
const itemIdle = "hover:bg-sky-50 text-slate-700";
const itemActive = "bg-sky-100 text-sky-700";

export default function InvestorDashboard() {
  const { user, logout } = useContext(AuthContext);
  if (user === undefined) return <p className="p-6">Loading dashboard…</p>;

  const [open, setOpen] = useState(true);

  const initialTab =
    (typeof window !== "undefined" &&
      localStorage.getItem("investor.selectedTab")) || "accreditation";
  const [selected, setSelected] = useState(initialTab);

  const [accredited, setAccredited] = useState(null);
  const [accError, setAccError] = useState("");

  // investor meta + readiness
  const [invMeta, setInvMeta] = useState({
    investor_type: null,
    parent_investor_id: null,
    dependents: [],
  });
  const [metaReady, setMetaReady] = useState(false);

  // ---- group admin detection (from AuthContext user) ----
  const normalizedUserType = (user?.user_type || "")
    .toString()
    .replace(/\s+/g, "")
    .toLowerCase();
  const isGroupAdmin = normalizedUserType === "groupadmin";
  const userFirstName =
    (user?.full_name || "").trim().split(/\s+/)[0] || "";

  // ---- investor notifications ----
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifCount, setNotifCount] = useState(0);
  const [notifItems, setNotifItems] = useState([]);
  const [notifLoading, setNotifLoading] = useState(false);
  const [notifError, setNotifError] = useState("");

  // accreditation check
  useEffect(() => {
    let alive = true;
    (async () => {
      setAccError("");
      try {
        const { data } = await api.get(`/api/investor/accreditation`, {
          headers: { Accept: "application/json" },
        });
        if (!alive) return;
        const ok = !!(data && data.selection && data.selection !== "not_yet");
        setAccredited(ok);
        setSelected(
          ok
            ? localStorage.getItem("investor.selectedTab") || "overview"
            : "accreditation"
        );
      } catch (e) {
        if (!alive) return;
        setAccredited(false);
        setSelected("accreditation");
        setAccError(
          e?.response?.data?.error ||
            (e?.response
              ? `Accreditation check failed (${e.response.status})`
              : "Unable to check accreditation.")
        );
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // load investor meta
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data } = await api.get("/api/investor/me", {
          headers: { Accept: "application/json" },
        });
        if (!alive) return;
        setInvMeta({
          investor_type: data?.investor_type ?? null,
          parent_investor_id: data?.parent_investor_id ?? null,
          dependents: Array.isArray(data?.dependents) ? data.dependents : [],
        });
      } finally {
        if (alive) setMetaReady(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // robust dependent + parent checks
  const isDependent = useMemo(() => {
    const t = String(invMeta.investor_type || "").trim().toLowerCase();
    const hasParent =
      invMeta.parent_investor_id !== null &&
      invMeta.parent_investor_id !== undefined;
    return t.startsWith("depend") || hasParent;
  }, [invMeta.investor_type, invMeta.parent_investor_id]);

  const hasDependents = useMemo(() => {
    return (
      Array.isArray(invMeta.dependents) && invMeta.dependents.length > 0
    );
  }, [invMeta.dependents]);

  // dependents: force portfolio tab
  useEffect(() => {
    if (!metaReady) return;
    if (isDependent) {
      if (selected !== "portfolio") setSelected("portfolio");
    }
  }, [metaReady, isDependent, selected]);

  // Inject/clear secure view-as header for dependents on the Portfolio tab
  useEffect(() => {
    const shouldViewParent =
      metaReady &&
      isDependent &&
      invMeta.parent_investor_id &&
      selected === "portfolio";
    if (shouldViewParent) {
      api.defaults.headers.common["X-View-As-Investor"] =
        String(invMeta.parent_investor_id);
    } else {
      delete api.defaults.headers.common["X-View-As-Investor"];
    }
    return () => {
      delete api.defaults.headers.common["X-View-As-Investor"];
    };
  }, [metaReady, isDependent, invMeta.parent_investor_id, selected]);

  // fix stored tab for dependents
  useEffect(() => {
    if (!metaReady) return;
    if (isDependent) {
      const stored = localStorage.getItem("investor.selectedTab");
      if (stored && stored !== "portfolio")
        localStorage.removeItem("investor.selectedTab");
    }
  }, [metaReady, isDependent]);

  useEffect(() => {
    if (selected === "accreditation" || accredited === true) {
      localStorage.setItem("investor.selectedTab", selected);
    }
  }, [selected, accredited]);

  // ---- Group admin: set/clear child view context when a member is chosen in My Group ----
  const handleSelectGroupInvestor = (member) => {
    try {
      const hasMember =
        !!member &&
        (member.name || member.investor_name || member.full_name);
      const name =
        (member &&
          (member.name || member.investor_name || member.full_name)) ||
        "";
      const id =
        (member &&
          (member.investor_id ?? member.id ?? member.investorId)) ?? null;

      if (hasMember && name) {
        // Persist hint so Overview / Portfolio / etc. load this child investor
        localStorage.setItem("investorHint", name);
        if (id !== null && id !== undefined) {
          localStorage.setItem("currentInvestorId", String(id));
        } else {
          localStorage.removeItem("currentInvestorId");
        }
      } else {
        // Back to investor list: clear any child context
        localStorage.removeItem("investorHint");
        localStorage.removeItem("currentInvestorId");
      }

      if (typeof window !== "undefined" && window.location) {
        const url = new URL(window.location.href);

        if (hasMember && name) {
          url.searchParams.set("investor", name);
          if (id !== null && id !== undefined) {
            url.searchParams.set("investorId", String(id));
          } else {
            url.searchParams.delete("investorId");
          }
        } else {
          url.searchParams.delete("investor");
          url.searchParams.delete("investorId");
        }

        // replace current URL (no history spam)
        window.history.replaceState({}, "", url.toString());
      }
    } catch {
      // ignore storage / history errors
    }
  };

  // ---- investor notifications: unread count + list ----
  useEffect(() => {
    let alive = true;

    const fetchCount = async () => {
      try {
        const { data } = await api.get("/api/notifications/unread-count", {
          headers: { Accept: "application/json" },
        });
        if (!alive) return;
        setNotifCount(data?.count || 0);
      } catch {
        if (!alive) return;
        // silently ignore; not critical
      }
    };

    fetchCount();
    const interval = setInterval(fetchCount, 60000);
    return () => {
      alive = false;
      clearInterval(interval);
    };
  }, []);

  const loadNotifications = async () => {
    setNotifLoading(true);
    setNotifError("");
    try {
      const { data } = await api.get("/api/notifications", {
        headers: { Accept: "application/json" },
      });
      setNotifItems(Array.isArray(data) ? data : []);
    } catch (e) {
      setNotifError(
        e?.response?.data?.error ||
          e?.message ||
          "Unable to load notifications."
      );
    } finally {
      setNotifLoading(false);
    }
  };

  const toggleNotif = () => {
    const next = !notifOpen;
    setNotifOpen(next);
    if (next) {
      loadNotifications();
    }
  };

  const markAllNotifRead = async () => {
    const ids = notifItems.filter((n) => !n.read_at).map((n) => n.id);
    if (!ids.length) {
      setNotifCount(0);
      return;
    }
    try {
      await api.post(
        "/api/notifications/mark-read",
        { ids },
        { headers: { "Content-Type": "application/json" } }
      );
      setNotifItems((items) =>
        items.map((n) =>
          n.read_at ? n : { ...n, read_at: new Date().toISOString() }
        )
      );
      setNotifCount(0);
    } catch (e) {
      setNotifError(
        e?.response?.data?.error ||
          e?.message ||
          "Failed to mark notifications as read."
      );
    }
  };

  // nav groups
  const navGroups = useMemo(() => {
    if (metaReady && isDependent) {
      return [
        {
          title: "INVESTMENTS",
          items: [{ id: "portfolio", label: "Portfolio", icon: Icon.portfolio }],
        },
        {
          title: "ACCOUNT",
          items: [{ id: "logout", label: "Logout", icon: Icon.logout }],
        },
      ];
    }

    const DASHBOARD = [
      { id: "overview", label: "Overview", icon: Icon.overview },
    ];

    const investmentsItems = [
      { id: "portfolio", label: "Portfolio", icon: Icon.portfolio },
    ];

    if (isGroupAdmin) {
      const label = userFirstName ? `${userFirstName}'s Group` : "My Group";
      investmentsItems.push({
        id: "group-members",
        label,
        icon: Icon.group,
      });
    }

    investmentsItems.push(
      { id: "statements", label: "Statements", icon: Icon.statements },
      { id: "documents", label: "Documents", icon: Icon.documents }
    );

    const PROFILE = [
      {
        id: "personalinformation",
        label: "Personal Information",
        icon: Icon.person,
      },
      { id: "accreditation", label: "Accreditation", icon: Icon.badge },
      { id: "contacts", label: "Contacts", icon: Icon.contacts },
      { id: "settings", label: "Settings", icon: Icon.settings },
    ];

    const showDependentsTab = metaReady && !isDependent && hasDependents;
    const DEP_GROUP = showDependentsTab
      ? [
          {
            title: "DEPENDENT",
            items: [
              { id: "dependents", label: "Dependent", icon: Icon.group },
            ],
          },
        ]
      : [];

    return [
      { title: "DASHBOARD", items: DASHBOARD },
      { title: "INVESTMENTS", items: investmentsItems },
      { title: "PROFILE", items: PROFILE },
      ...DEP_GROUP,
      {
        title: "ACCOUNT",
        items: [{ id: "logout", label: "Logout", icon: Icon.logout }],
      },
    ];
  }, [metaReady, isDependent, hasDependents, isGroupAdmin, userFirstName]);

  const changeTab = (id) => {
    if (id === "logout") {
      logout();
      return;
    }
    if (metaReady && isDependent && id !== "portfolio") return;
    if (accredited === false && !isDependent && id !== "accreditation") {
      setSelected("accreditation");
      return;
    }
    const canSeeDependents = metaReady && !isDependent && hasDependents;
    if (id === "dependents" && !canSeeDependents) return;

    setSelected(id);

    // 🔑 IMPORTANT: if we are leaving the My Group area, clear any
    // child-investor context so main dashboard tabs show only the group admin.
    if (id !== "group-members") {
      try {
        localStorage.removeItem("investorHint");
        localStorage.removeItem("currentInvestorId");
      } catch {
        // ignore storage errors
      }

      if (typeof window !== "undefined" && window.location) {
        try {
          const url = new URL(window.location.href);
          url.searchParams.delete("investor");
          url.searchParams.delete("investorId");
          window.history.replaceState({}, "", url.toString());
        } catch {
          // ignore URL errors
        }
      }
    }

    if (
      window?.matchMedia &&
      window.matchMedia("(max-width: 1023px)").matches
    )
      setOpen(false);
  };

  const isLocked = (id) => {
    if (metaReady && isDependent) return id !== "portfolio" && id !== "logout";
    return accredited === false && id !== "accreditation" && id !== "logout";
  };

  return (
    <div className="min-h-screen bg-slate-100 flex flex-col">
      <header className="flex items-center justify-between gap-3 bg-white border-b px-3 sm:px-4 md:px-6 py-3 sticky top-0 z-40">
        <div className="flex items-center gap-3">
          <button
            type="button"
            className="inline-flex items-center justify-center p-2 rounded-md border border-slate-300 text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-sky-500"
            onClick={() => setOpen((v) => !v)}
            aria-label={open ? "Close menu" : "Open menu"}
          >
            {open ? <Icon.close /> : <Icon.menu />}
          </button>
          <h1 className="text-base sm:text-lg md:text-2xl font-semibold text-blue-600">
            Investor Panel
          </h1>
        </div>

        {/* Notification bell */}
        <div className="flex items-center gap-3">
          <div className="relative">
            <button
              type="button"
              onClick={toggleNotif}
              className="relative inline-flex items-center justify-center rounded-full border border-slate-300 bg-white p-2 text-slate-600 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-sky-500"
              aria-label="Investor notifications"
            >
              <Icon.bell />
              {notifCount > 0 && (
                <span className="absolute -top-1 -right-1 inline-flex items-center justify-center rounded-full bg-rose-500 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                  {notifCount > 9 ? "9+" : notifCount}
                </span>
              )}
            </button>

            {notifOpen && (
              <div className="absolute right-0 mt-2 w-72 rounded-xl border border-slate-200 bg-white shadow-lg z-[100]">
                <div className="flex items-center justify-between px-3 py-2 border-b border-slate-100">
                  <span className="text-xs font-semibold text-slate-600">
                    Notifications
                  </span>
                  <button
                    type="button"
                    onClick={markAllNotifRead}
                    className="text-[11px] text-sky-600 hover:underline"
                  >
                    Mark all read
                  </button>
                </div>
                <div className="max-h-72 overflow-y-auto">
                  {notifLoading ? (
                    <div className="px-3 py-3 text-xs text-slate-500">
                      Loading…
                    </div>
                  ) : notifError ? (
                    <div className="px-3 py-3 text-xs text-rose-600">
                      {notifError}
                    </div>
                  ) : !notifItems.length ? (
                    <div className="px-3 py-3 text-xs text-slate-500">
                      No notifications yet.
                    </div>
                  ) : (
                    notifItems.map((n) => (
                      <div
                        key={n.id}
                        className={`px-3 py-2 text-xs border-b border-slate-50 last:border-0 ${
                          !n.read_at ? "bg-slate-50" : ""
                        }`}
                      >
                        <div className="font-semibold text-slate-700">
                          {n.title || "Notification"}
                        </div>
                        {n.message && (
                          <div className="mt-0.5 text-slate-600">
                            {n.message}
                          </div>
                        )}
                        <div className="mt-0.5 flex justify-between items-center text-[10px] text-slate-400">
                          <span>
                            {n.created_at
                              ? new Date(n.created_at).toLocaleString()
                              : ""}
                          </span>
                          {n.link_url && (
                            <a
                              href={n.link_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-sky-600 hover:underline"
                            >
                              View
                            </a>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

      {metaReady && isDependent && selected === "portfolio" && (
        <div className="bg-sky-50 text-sky-800 border-b border-sky-200 px-4 py-2 text-sm">
          You are a dependent investor. This Portfolio shows your parent
          investor’s data.
        </div>
      )}

      <div className="flex-1 flex relative">
        {open && (
          <div
            className="fixed inset-0 bg-black/25 z-30 lg:hidden"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
        )}

        <aside
          className={[
            "fixed lg:static z-40 lg:z-0 inset-y-0 left-0 w-60 bg-white border-r",
            "transform transition-transform duration-200 ease-in-out",
            open ? "translate-x-0" : "-translate-x-full",
          ].join(" ")}
          aria-label="Sidebar navigation"
        >
          <nav className="h-full overflow-y-auto px-3 py-4 space-y-6">
            {navGroups.map((g) => (
              <div key={g.title}>
                <div className="font-semibold text-slate-400 uppercase text-[11px] tracking-wide mb-2">
                  {g.title}
                </div>
                <ul className="space-y-1">
                  {g.items.map((item) => {
                    const Active = selected === item.id;
                    const disabled = isLocked(item.id);
                    const Ico = item.icon;
                    return (
                      <li key={item.id}>
                        <button
                          className={`${itemBase} ${
                            Active ? itemActive : itemIdle
                          } ${
                            disabled ? "opacity-50 cursor-not-allowed" : ""
                          }`}
                          onClick={() =>
                            !disabled ? changeTab(item.id) : null
                          }
                          aria-disabled={disabled ? "true" : "false"}
                          title={
                            disabled
                              ? "Not available for this account"
                              : item.label
                          }
                        >
                          <span className="shrink-0 leading-none inline-flex items-center">
                            <Ico />
                          </span>
                          <span className="truncate">{item.label}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>
        </aside>

        <main className="flex-1 px-3 sm:px-4 md:px-6 lg:px-8 py-4 z-10">
          {!isDependent && accredited === false && (
            <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 text-amber-800 px-4 py-3 text-sm">
              Please complete your <strong>Accreditation</strong> to access the
              rest of the dashboard.
            </div>
          )}
          {accError && (
            <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 px-4 py-3 text-sm">
              {accError}
            </div>
          )}

          <div className="w-full">
            {!isDependent && selected === "overview" && <InvestorOverview />}

            {selected === "portfolio" && <Portfolio />}

            {!isDependent && isGroupAdmin && selected === "group-members" && (
              <GroupMembersTab onSelectInvestor={handleSelectGroupInvestor} />
            )}

            {!isDependent && selected === "statements" && <Statements />}
            {!isDependent && selected === "documents" && <Documents />}
            {!isDependent && selected === "personalinformation" && (
              <PersonalInformation />
            )}
            {!isDependent && selected === "contacts" && <Contacts />}
            {!isDependent && selected === "settings" && <Settings />}
            {selected === "accreditation" && !isDependent && (
              <Accreditation onAccredited={setAccredited} />
            )}
            {!isDependent && hasDependents && selected === "dependents" && (
              <DependentsTab />
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

/* ---------------------- Group members tab component ---------------------- */

const CHILD_TABS = [
  { id: "overview", label: "Overview" },
  { id: "portfolio", label: "Portfolio" },
  { id: "statements", label: "Statements" },
  { id: "documents", label: "Documents" },
  { id: "personalinformation", label: "Personal Information" },
  { id: "accreditation", label: "Accreditation" },
  { id: "contacts", label: "Contacts" },
  { id: "settings", label: "Settings" },
];

const GroupMembersTab = ({ onSelectInvestor }) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [members, setMembers] = useState([]);

  const [selectedMember, setSelectedMember] = useState(null);
  const [activeTab, setActiveTab] = useState("overview");

  useEffect(() => {
    const fetchMembers = async () => {
      try {
        setLoading(true);
        setError(null);

        // CSRF-based group-admin endpoint
        const { data } = await api.get("/api/group-admin/my-group", {
          headers: { Accept: "application/json" },
        });

        const raw = data || {};
        const list = Array.isArray(raw.members)
          ? raw.members
          : Array.isArray(raw.investors)
          ? raw.investors
          : [];

        const normalized = list.map((m) => ({
          id: m.id ?? m.investor_id,
          investor_id: m.id ?? m.investor_id,
          name: m.name,
          email: m.email,
          added_at: m.added_at || null,
        }));

        setMembers(normalized);
      } catch (err) {
        setError(
          err?.response?.data?.error ||
            err?.message ||
            "Failed to load group investors."
        );
      } finally {
        setLoading(false);
      }
    };

    fetchMembers();
  }, []);

  const handleClickInvestor = (member) => {
    setSelectedMember(member);
    setActiveTab("overview");
    if (onSelectInvestor) {
      // send the full member object so dashboard can set both name + id
      onSelectInvestor(member);
    }
  };

  const handleBackToList = () => {
    setSelectedMember(null);
    setActiveTab("overview");
    if (onSelectInvestor) {
      // clears child context in dashboard
      onSelectInvestor(null);
    }
  };

  if (loading) {
    return <p className="text-sm text-slate-600">Loading group investors…</p>;
  }

  if (error) {
    return (
      <div className="rounded-md border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {error}
      </div>
    );
  }

  if (!members.length) {
    return (
      <div className="rounded-md border border-slate-100 bg-white px-4 py-3 text-sm text-slate-600">
        No investors have been added to your group yet.
      </div>
    );
  }

  // DETAIL MODE (viewing a specific child)
  if (selectedMember) {
    return (
      <div className="rounded-xl border border-slate-100 bg-white">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <div>
            <div className="text-xs font-semibold text-sky-700 uppercase tracking-wide">
              Viewing child investor
            </div>
            <div className="text-base font-semibold text-slate-900">
              {selectedMember.name}
            </div>
            <div className="text-xs text-slate-500">{selectedMember.email}</div>
          </div>
          <button
            type="button"
            onClick={handleBackToList}
            className="inline-flex items-center px-3 py-1.5 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 bg-white hover:bg-slate-50"
          >
            ← Back to investor list
          </button>
        </div>

        <div className="border-b border-slate-100 flex flex-wrap items-center gap-1 px-4 pt-2">
          {CHILD_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-2 text-xs sm:text-sm border-b-2 -mb-px transition ${
                activeTab === tab.id
                  ? "border-sky-500 text-sky-700 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="p-4 sm:p-6">
          {activeTab === "overview" && <InvestorOverview />}
          {activeTab === "portfolio" && <Portfolio />}
          {activeTab === "statements" && <Statements />}
          {activeTab === "documents" && <Documents />}
          {activeTab === "personalinformation" && <PersonalInformation />}
          {activeTab === "accreditation" && <Accreditation />}
          {activeTab === "contacts" && <Contacts />}
          {activeTab === "settings" && <Settings />}
        </div>
      </div>
    );
  }

  // LIST MODE
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-4 space-y-3">
      <h2 className="text-sm sm:text-base font-semibold text-slate-800">
        Investors in your group
      </h2>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-xs sm:text-sm">
          <thead className="border-b border-slate-100 text-slate-500">
            <tr>
              <th className="py-2 pr-4 font-medium">Name</th>
              <th className="py-2 px-4 font-medium">Email</th>
              <th className="py-2 px-4 font-medium">Added</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {members.map((m) => (
              <tr key={m.investor_id ?? m.id}>
                <td className="py-2 pr-4 text-slate-800">
                  <button
                    type="button"
                    onClick={() => handleClickInvestor(m)}
                    className="text-sky-700 hover:underline"
                  >
                    {m.name}
                  </button>
                </td>
                <td className="py-2 px-4 text-sky-700">{m.email}</td>
                <td className="py-2 px-4 text-slate-500">
                  {m.added_at
                    ? new Date(m.added_at).toLocaleDateString()
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

/* ----------------- Dependents tab (unchanged) -------------- */

function DependentsTab() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [posting, setPosting] = useState({});
  const [toast, setToast] = useState({ type: "", msg: "" });

  useEffect(() => {
    loadRows();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadRows = async () => {
    setErr("");
    setLoading(true);
    try {
      const { data } = await api.get("/api/investors/dependents", {
        headers: { Accept: "application/json" },
      });
      const list = Array.isArray(data)
        ? data
        : Array.isArray(data?.items)
        ? data.items
        : Array.isArray(data?.data)
        ? data.data
        : [];
      setRows(list);
    } catch (e) {
      setErr(
        e?.response?.data?.error ||
          e?.message ||
          "Unable to load dependents."
      );
    } finally {
      setLoading(false);
    }
  };

  const requestDelete = async (childId) => {
    if (!childId) return;
    setPosting((p) => ({ ...p, [childId]: true }));
    setToast({ type: "", msg: "" });
    try {
      await api.post(
        "/api/deletion-requests",
        { investor_id: childId },
        { headers: { "Content-Type": "application/json" } }
      );
      setRows((rs) =>
        rs.map((r) =>
          r.id === childId ? { ...r, delete_request_status: "pending" } : r
        )
      );
      setToast({ type: "success", msg: "Delete request sent to admin." });
    } catch (e) {
      setToast({
        type: "error",
        msg:
          e?.response?.data?.error ||
          e?.message ||
          "Request failed.",
      });
    } finally {
      setPosting((p) => ({ ...p, [childId]: false }));
      setTimeout(() => setToast({ type: "", msg: "" }), 3500);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Dependent Accounts</h2>

      {toast.msg && (
        <div
          className={`rounded-lg border px-4 py-3 text-sm ${
            toast.type === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-rose-200 bg-rose-50 text-rose-700"
          }`}
        >
          {toast.msg}
        </div>
      )}

      {err && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 text-rose-700 px-4 py-3 text-sm">
          {err}
        </div>
      )}

      {loading ? (
        <div className="rounded-lg border p-6 text-sm text-slate-600">
          Loading…
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-lg border p-6 text-sm text-slate-600">
          No dependent accounts found.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-gray-50 text-gray-700">
              <tr>
                <th className="px-4 py-3 font-medium">Investor</th>
                <th className="px-4 py-3 font-medium">Email</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Relation</th>
                <th className="px-4 py-3 font-medium">Delete Request</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((r) => {
                const status = (r.delete_request_status || "").toLowerCase();
                const busy = !!posting[r.id];
                const relationship =
                  r.parent_relationship || r.relationship || "—";

                return (
                  <tr key={r.id || r.investor_id}>
                    <td className="px-4 py-3">{r.name || "—"}</td>
                    <td className="px-4 py-3">{r.email || "—"}</td>
                    <td className="px-4 py-3">
                      {r.investor_type || "Depends"}
                    </td>
                    <td className="px-4 py-3">{relationship}</td>
                    <td className="px-4 py-3">
                      {status === "pending" ? (
                        <span className="inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-900">
                          Pending
                        </span>
                      ) : status === "approved" ? (
                        <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-900">
                          Approved
                        </span>
                      ) : status === "rejected" ? (
                        <span className="inline-flex items-center rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs text-rose-700">
                          Rejected
                        </span>
                      ) : (
                        <button
                          onClick={() => requestDelete(r.id)}
                          disabled={busy}
                          className="rounded-lg border px-2.5 py-1 text-xs hover:bg-gray-50 disabled:opacity-60"
                          title="Ask admin to remove this dependent account"
                        >
                          {busy ? "Sending…" : "Request delete"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
