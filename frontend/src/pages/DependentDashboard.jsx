import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api from "../services/api";

// Reuse your existing tabs
import InvestorOverview from "../components/tabs/InvestorOverview";
import Portfolio from "../components/investments/Portfolio";

const IconBack = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);
const IconExit = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path d="M6 18L18 6M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

export default function DependentDashboard() {
  const { id } = useParams();                 // child (dependent) investor id
  const navigate = useNavigate();
  const childId = useMemo(() => (id ? String(id) : ""), [id]);

  const [active, setActive] = useState("overview"); // "overview" | "portfolio"
  const [meta, setMeta] = useState({ name: "", email: "", investor_type: "", parent_investor_id: null });
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  // Set header for ALL requests under this page; restore on unmount
  useEffect(() => {
    const prev = api.defaults.headers.common["X-View-As-Investor"];
    api.defaults.headers.common["X-View-As-Investor"] = childId;
    return () => {
      if (prev) api.defaults.headers.common["X-View-As-Investor"] = prev;
      else delete api.defaults.headers.common["X-View-As-Investor"];
    };
  }, [childId]);

  // Load the child “me” using secure guard
  useEffect(() => {
    let alive = true;
    (async () => {
      setErr("");
      setLoading(true);
      try {
        const { data } = await api.get("/api/investor/me", { headers: { Accept: "application/json" } });
        if (!alive) return;
        setMeta({
          name: data?.name || "",
          email: data?.email || "",
          investor_type: data?.investor_type || "",
          parent_investor_id: data?.parent_investor_id ?? null,
        });
      } catch (e) {
        if (!alive) return;
        const status = e?.response?.status;
        setErr(
          e?.response?.data?.error ||
          (status === 403 ? "You are not authorized to view this dependent." :
           status === 404 ? "Dependent account not found." :
           "Unable to load dependent.")
        );
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [childId]);

  const Title = () => (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <button
          onClick={() => navigate(-1)}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-md border border-slate-300 text-slate-700 hover:bg-slate-50"
          title="Back"
        >
          <IconBack /> Back
        </button>
        <h1 className="text-xl md:text-2xl font-semibold text-blue-600">
          Viewing Dependent — {meta.name || `#${childId}`}
        </h1>
      </div>
      <button
        onClick={() => navigate("/dashboard")}
        className="inline-flex items-center gap-2 px-3 py-2 rounded-md bg-rose-600 text-white hover:bg-rose-700"
        title="Exit child view"
      >
        <IconExit /> Exit
      </button>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="bg-white border-b px-3 sm:px-4 md:px-6 py-3 sticky top-0 z-40">
        <Title />
        <p className="mt-2 text-sm text-sky-700 bg-sky-50 border border-sky-200 rounded px-3 py-2">
          You’re securely viewing your dependent’s dashboard. Only Overview and Portfolio are available.
        </p>
      </header>

      <main className="px-3 sm:px-4 md:px-6 lg:px-8 py-4">
        {loading && <div className="rounded-lg border p-6 text-sm text-slate-600">Loading dependent…</div>}
        {!loading && err && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 text-rose-700 px-4 py-3 text-sm">{err}</div>
        )}
        {!loading && !err && (
          <div className="space-y-4">
            {/* Child banner card */}
            <div className="rounded-lg border bg-blue-50 text-slate-700 px-4 py-3">
              <div className="font-medium">
                Viewing as <span className="text-slate-900">{meta.name || "Dependent"}</span>
              </div>
              <div className="text-sm text-slate-600">
                {meta.email ? <span>{meta.email} • </span> : null}
                Type: {meta.investor_type || "Depends"}
              </div>
            </div>

            {/* Two-tab nav */}
            <div className="flex items-center gap-2 border-b">
              <button
                className={`px-3 py-2 text-sm border-b-2 ${active === "overview" ? "border-blue-600 text-blue-700 font-medium" : "border-transparent text-slate-600 hover:text-slate-800"}`}
                onClick={() => setActive("overview")}
              >
                Overview
              </button>
              <button
                className={`px-3 py-2 text-sm border-b-2 ${active === "portfolio" ? "border-blue-600 text-blue-700 font-medium" : "border-transparent text-slate-600 hover:text-slate-800"}`}
                onClick={() => setActive("portfolio")}
              >
                Portfolio
              </button>
            </div>

            {/* Tab bodies (reuse your existing components; they now fetch as child via header) */}
            {active === "overview" && <InvestorOverview />}
            {active === "portfolio" && <Portfolio />}
          </div>
        )}
      </main>
    </div>
  );
}
