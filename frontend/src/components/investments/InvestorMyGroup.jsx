// frontend/src/pages/InvestorMyGroup.jsx
import React, { useEffect, useState, useMemo } from "react";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "portfolio", label: "Portfolio" },
  { id: "statements", label: "Statements" },
  { id: "documents", label: "Documents" },
  { id: "personal", label: "Personal Information" },
  { id: "accreditation", label: "Accreditation" },
  { id: "contacts", label: "Contacts" },
  { id: "settings", label: "Settings" },
];

const fmtUSD = (n) =>
  `$${Number(n || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const fmtPct = (n) =>
  n === null || n === undefined || Number.isNaN(Number(n))
    ? "—"
    : `${Number(n).toFixed(2)}%`;

/** Tiny helper for inner scroll styling */
const InnerScrollStyles = () => (
  <style>{`
    .inner-x-scroll{overflow-x:auto;overflow-y:hidden;max-width:100%}
    .inner-x-scroll::-webkit-scrollbar{height:10px}
    .inner-x-scroll::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:8px}
    .inner-x-scroll::-webkit-scrollbar-track{background:#f1f5f9}
  `}</style>
);

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
  // Only attach XSRF for non-GET, or when explicitly forced
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

/**
 * MAIN PAGE
 * - Shows investor list
 * - On click → detail mode with horizontal tabs
 */
export default function InvestorMyGroup() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [investors, setInvestors] = useState([]);
  const [selectedInvestor, setSelectedInvestor] = useState(null);
  const [activeTab, setActiveTab] = useState("overview");
  const [isGroupAdmin, setIsGroupAdmin] = useState(false);

  // Load group investors from cookie-authenticated endpoint
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        setLoading(true);
        setError("");

        // New backend endpoint for group-admin self view:
        // GET /api/group-admin/my-group
        const res = await xsrfFetch("/api/group-admin/my-group", {
          method: "GET",
        });
        const json = await res.json();

        // If 403, user is not a group admin
        if (res.status === 403) {
          if (!cancelled) {
            setIsGroupAdmin(false);
            setInvestors([]);
          }
          return;
        }

        if (!res.ok || json.ok === false) {
          throw new Error(json?.error || `HTTP ${res.status}`);
        }

        if (!cancelled) {
          setIsGroupAdmin(true);
          const members = Array.isArray(json.members) ? json.members : [];
          const list = members.map((m) => ({
            id: m.investor_id ?? m.id,
            name: m.name,
            email: m.email,
            is_admin: !!m.is_admin,
          }));
          setInvestors(list);
        }
      } catch (err) {
        console.error("Failed to load group investors", err);
        if (!cancelled) {
          setError(err.message || "Failed to load group investors");
          setInvestors([]);
          setIsGroupAdmin(false);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleSelectInvestor = (inv) => {
    setSelectedInvestor(inv);
    setActiveTab("overview");
  };

  const handleBackToList = () => {
    setSelectedInvestor(null);
  };

  const hasInvestors = useMemo(
    () => Array.isArray(investors) && investors.length > 0,
    [investors]
  );

  return (
    <div className="space-y-6">
      <InnerScrollStyles />

      {/* LIST MODE */}
      {!selectedInvestor && (
        <>
          <div className="bg-white rounded-xl shadow p-4 flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold text-slate-800">
                  My Group
                </div>
                <div className="text-xs text-slate-500">
                  {isGroupAdmin
                    ? "You are a Group Investor Admin. Select an investor below to view their dashboard."
                    : "You do not appear to be a Group Investor Admin."}
                </div>
              </div>
            </div>
          </div>

          {loading && (
            <div className="bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-sm text-slate-600">
              Loading investors in your group…
            </div>
          )}

          {error && (
            <div className="bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          )}

          {!loading && !error && !hasInvestors && (
            <div className="bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-sm text-slate-600">
              No investors have been added to your group yet.
            </div>
          )}

          {!loading && !error && hasInvestors && (
            <div className="bg-white rounded-xl shadow p-4">
              <div className="overflow-x-auto inner-x-scroll">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-500 border-b">
                      <th className="py-2 pr-4">Name</th>
                      <th className="py-2 pr-4">Email</th>
                      <th className="py-2 pr-4">Role</th>
                      <th className="py-2 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {investors.map((inv) => (
                      <tr
                        key={inv.id}
                        className="border-b last:border-b-0 hover:bg-slate-50"
                      >
                        <td className="py-2 pr-4 text-slate-800">
                          {inv.name || "—"}
                        </td>
                        <td className="py-2 pr-4 text-slate-600">
                          {inv.email || "—"}
                        </td>
                        <td className="py-2 pr-4 text-slate-600">
                          {inv.is_admin ? "Group Admin" : "Investor"}
                        </td>
                        <td className="py-2 text-right">
                          <button
                            className="inline-flex items-center px-3 py-1.5 rounded-lg border border-sky-500 text-xs font-semibold text-sky-700 bg-white hover:bg-sky-50"
                            onClick={() => handleSelectInvestor(inv)}
                          >
                            View investor dashboard
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* DETAIL MODE */}
      {selectedInvestor && (
        <div className="space-y-4">
          {/* Header + Back */}
          <div className="bg-sky-50 border border-sky-100 rounded-xl px-4 py-3 flex flex-col md:flex-row md:items-center md:justify-between gap-2">
            <div>
              <div className="text-xs font-medium text-sky-700 uppercase tracking-wide">
                Viewing child investor
              </div>
              <div className="text-base font-semibold text-slate-900">
                {selectedInvestor.name}
              </div>
              <div className="text-xs text-slate-600">
                {selectedInvestor.email}
              </div>
            </div>
            <button
              onClick={handleBackToList}
              className="self-start md:self-auto inline-flex items-center px-3 py-1.5 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 bg-white hover:bg-slate-50"
            >
              ← Back to investor list
            </button>
          </div>

          {/* Horizontal Tabs */}
          <div className="bg-white rounded-xl shadow">
            <div className="border-b flex flex-wrap items-center gap-1 px-4 pt-3">
              {TABS.map((tab) => (
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
              {activeTab === "overview" && (
                <ChildInvestorOverviewTab investor={selectedInvestor} />
              )}

              {activeTab === "portfolio" && (
                <PlaceholderTab
                  label="Portfolio"
                  investor={selectedInvestor}
                />
              )}

              {activeTab === "statements" && (
                <PlaceholderTab
                  label="Statements"
                  investor={selectedInvestor}
                />
              )}

              {activeTab === "documents" && (
                <PlaceholderTab
                  label="Documents"
                  investor={selectedInvestor}
                />
              )}

              {activeTab === "personal" && (
                <PlaceholderTab
                  label="Personal Information"
                  investor={selectedInvestor}
                />
              )}

              {activeTab === "accreditation" && (
                <PlaceholderTab
                  label="Accreditation"
                  investor={selectedInvestor}
                />
              )}

              {activeTab === "contacts" && (
                <PlaceholderTab
                  label="Contacts"
                  investor={selectedInvestor}
                />
              )}

              {activeTab === "settings" && (
                <PlaceholderTab
                  label="Settings"
                  investor={selectedInvestor}
                />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * OVERVIEW TAB
 * - Uses the same backend as the normal investor overview:
 *   /api/metrics/investor-overview?investor=<child-name>
 */
function ChildInvestorOverviewTab({ investor }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!investor?.name) return;
    let cancelled = false;

    (async () => {
      try {
        setLoading(true);
        setError("");

        const params = new URLSearchParams({
          sheet: "bCAS (Q4 Adj)", // keep in sync with InvestorOverview.jsx
          investor: investor.name,
        });

        const res = await xsrfFetch(
          `/api/metrics/investor-overview?${params.toString()}`,
          { method: "GET" }
        );
        const j = await res.json();
        if (!res.ok) throw new Error(j?.error || `HTTP ${res.status}`);

        if (!cancelled) setData(j);
      } catch (err) {
        console.error("Child investor overview error:", err);
        if (!cancelled)
          setError(err.message || "Failed to load investor overview");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [investor]);

  if (loading)
    return (
      <div className="text-sm text-slate-600">Loading overview…</div>
    );
  if (error)
    return (
      <div className="text-sm text-rose-600">
        {error || "No data available for this investor."}
      </div>
    );
  if (!data)
    return (
      <div className="text-sm text-slate-600">
        No overview data available for this investor.
      </div>
    );

  const initialValue = Number(data.initial_value || 0);
  const currentValue = Number(data.current_value || 0);
  const roiPct = Number(data.roi_pct || 0);
  const moic = Number(data.moic || 0);
  const irrPct =
    data.irr_pct !== undefined && data.irr_pct !== null
      ? Number(data.irr_pct)
      : null;
  const distributed = Number(data.distributed || data.distributions || 0);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-slate-50 rounded-xl border border-slate-200 p-4">
          <div className="text-xs text-slate-500 uppercase font-medium">
            Initial value
          </div>
          <div className="mt-1 text-2xl font-semibold text-slate-900">
            {fmtUSD(initialValue)}
          </div>
        </div>
        <div className="bg-slate-50 rounded-xl border border-slate-200 p-4">
          <div className="text-xs text-slate-500 uppercase font-medium">
            Current value
          </div>
          <div className="mt-1 text-2xl font-semibold text-slate-900">
            {fmtUSD(currentValue)}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl shadow-sm p-4">
          <div className="text-xs text-slate-500 uppercase font-medium">
            ROI
          </div>
          <div className="mt-1 text-xl font-semibold text-emerald-600">
            {roiPct >= 0 ? "+" : ""}
            {roiPct.toFixed(2)}%
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-4">
          <div className="text-xs text-slate-500 uppercase font-medium">
            MOIC
          </div>
          <div className="mt-1 text-xl font-semibold text-slate-900">
            {moic.toFixed(2)}x
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-4">
          <div className="text-xs text-slate-500 uppercase font-medium">
            IRR (annualized)
          </div>
          <div className="mt-1 text-xl font-semibold text-slate-900">
            {fmtPct(irrPct)}
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-4">
          <div className="text-xs text-slate-500 uppercase font-medium">
            Distributed
          </div>
          <div className="mt-1 text-xl font-semibold text-slate-900">
            {fmtUSD(distributed)}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * PLACEHOLDER TAB CONTENT
 * - Replace with your existing components (Portfolio, Statements, etc.)
 *   and pass the selected investor via props or query param.
 */
function PlaceholderTab({ label, investor }) {
  return (
    <div className="text-sm text-slate-600">
      <div className="font-semibold text-slate-800 mb-1">
        {label}
      </div>
      <p>
        This is the <strong>{label}</strong> tab for{" "}
        <strong>{investor.name}</strong>.
      </p>
      <p className="mt-2 text-xs text-slate-500">
        TODO: Reuse your existing “{label}” page here, either by:
        <br />
        • importing the component and passing{" "}
        <code>viewAsInvestor={investor}</code>, or
        <br />
        • navigating to a dedicated route like{" "}
        <code>?investor={encodeURIComponent(investor.name)}</code>.
      </p>
    </div>
  );
}
