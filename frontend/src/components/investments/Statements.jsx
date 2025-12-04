import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { IoClose } from "react-icons/io5";
import api from "../../services/api"; // use "@/services/api" if you have a Vite alias

/* ---------- tiny utils ---------- */
const cx = (...xs) => xs.filter(Boolean).join(" ");
const toCurrency = (n) =>
  n == null || Number.isNaN(n)
    ? "—"
    : new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: "USD",
      }).format(Number(n));

const toPct = (n, d = 4) =>
  n == null || Number.isNaN(n) ? "—" : `${Number(n).toFixed(d)}%`;

const toISODate = (d) => {
  if (!d) return "";
  const dt = d instanceof Date ? d : new Date(d);
  return Number.isNaN(dt.getTime()) ? "" : dt.toISOString().slice(0, 10);
};

const getExt = (name = "") => {
  const m = (name || "").toLowerCase().match(/\.([a-z0-9]+)$/i);
  return m ? m[1] : "";
};

function downloadCSV(filename, rows) {
  const csv = rows
    .map((r) =>
      r
        .map((v) => {
          const s = v == null ? "" : String(v);
          return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
        })
        .join(","),
    )
    .join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 600);
}

/* ---------- shared view-as helper ---------- */
function resolveViewAsInvestorId() {
  if (typeof window === "undefined") return null;
  try {
    const url = new URL(window.location.href);
    const fromQuery = url.searchParams.get("investorId");
    const fromStorage = window.localStorage.getItem("currentInvestorId");
    const v = fromQuery || fromStorage;
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

/* ---------- component ---------- */
export default function Statements({
  profiles = [],
  adminView = false,
  investorId: propInvestorId = null,
}) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  // extra: documents shared as "statement"
  const [statementDocs, setStatementDocs] = useState([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [docsErr, setDocsErr] = useState("");

  // who am I (only to know when auth is ready)
  const [me, setMe] = useState({ ready: false, user: null, investor: null });

  // filters / ui (controls for profile & tabs are NOT rendered anymore, but state remains for logic)
  const [profileFilter, setProfileFilter] = useState("All profiles");
  const [tab, setTab] = useState("All");
  const [query, setQuery] = useState("");
  const [dueAsc, setDueAsc] = useState(true);
  const [showColumnsMenu, setShowColumnsMenu] = useState(false);
  const columnsMenuRef = useRef(null);

  // actions menu
  const [openActionId, setOpenActionId] = useState(null);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 });
  const actionsTriggerRef = useRef(null);
  const floatingMenuRef = useRef(null);

  // drawer/detail for generated statements
  const [detailId, setDetailId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailErr, setDetailErr] = useState("");
  const [pdfUrl, setPdfUrl] = useState(""); // preview URL (Blob)
  const [pdfErr, setPdfErr] = useState(""); // preview error text
  const pdfObjectUrlRef = useRef(null); // track blob URL to revoke

  // quarter generator controls (UI removed, function kept for future admin screen reuse)
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [quarter, setQuarter] = useState(
    Math.floor(today.getMonth() / 3) + 1,
  );
  const [entityName, setEntityName] = useState(
    "Elpis Opportunity Fund LP",
  );
  const [genBusy, setGenBusy] = useState(false);

  // visible columns
  const [visible, setVisible] = useState({
    name: true,
    investor: true,
    entity: true,
    dueDate: true,
    status: true,
    amountDue: true,
    paidDate: true,
    download: true,
    actions: true,
  });

  // viewer for uploaded statement documents (same style as admin Documents)
  const [docViewerOpen, setDocViewerOpen] = useState(false);
  const [docViewerDoc, setDocViewerDoc] = useState(null);
  const [docViewerUrl, setDocViewerUrl] = useState(null);
  const [docViewerText, setDocViewerText] = useState(null);
  const [docViewerLoading, setDocViewerLoading] = useState(false);

  /* ---------------- identity (ready flag only) ---------------- */
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data } = await api.get("/auth/me", {
          headers: { Accept: "application/json" },
        });
        if (!alive) return;
        setMe({
          ready: true,
          user: data?.user || null,
          investor: data?.investor || null,
        });
      } catch {
        if (!alive) return;
        setMe({ ready: true, user: null, investor: null });
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // --- decide WHEN to send investor_id ---
  const viewAsInvestorId = resolveViewAsInvestorId();

  // Only send investor_id when:
  //  - adminView + explicit propInvestorId (admin “view as”)
  //  - or we are viewing a child from My Group (viewAsInvestorId)
  const effectiveInvestorId =
    adminView && propInvestorId != null && propInvestorId !== undefined
      ? propInvestorId
      : viewAsInvestorId != null
      ? viewAsInvestorId
      : null;

  /* ---------------- table loading ---------------- */
  async function fetchRows() {
    setLoading(true);
    setErr("");
    try {
      // For embedded admin view or My Group child view,
      // scope by that investor_id. For normal investors, let
      // backend infer from logged-in account (no extra param).
      const params = effectiveInvestorId
        ? { investor_id: effectiveInvestorId }
        : undefined;

      const { data } = await api.get("/api/statements", {
        ...(params ? { params } : {}),
      });

      // Robust handling of different response shapes
      let list = [];
      if (Array.isArray(data)) {
        list = data;
      } else if (data && typeof data === "object") {
        if (Array.isArray(data.items)) list = data.items;
        else if (Array.isArray(data.data)) list = data.data;
        else if (Array.isArray(data.statements)) list = data.statements;
      }

      setRows(list);
    } catch (e) {
      setErr(String(e?.response?.data?.error || e.message || e));
    } finally {
      setLoading(false);
    }
  }

  // fetch documents shared as "statement"
  async function fetchStatementDocs() {
    setDocsLoading(true);
    setDocsErr("");
    try {
      const params = { share_type: "statement" };
      if (effectiveInvestorId) {
        params.investor_id = effectiveInvestorId;
      }

      const { data } = await api.get("/api/documents", { params });

      let list = [];
      if (Array.isArray(data?.documents)) {
        list = data.documents;
      } else if (Array.isArray(data)) {
        list = data;
      }

      setStatementDocs(list);
    } catch (e) {
      setDocsErr(String(e?.response?.data?.error || e.message || e));
    } finally {
      setDocsLoading(false);
    }
  }

  useEffect(() => {
    if (me.ready) {
      fetchRows();
      fetchStatementDocs();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me.ready, effectiveInvestorId, adminView]);

  /* ---------------- client filtering/sorting ---------------- */
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let out = rows.map((r) => ({ ...r, _due: new Date(r.dueDate) }));
    if (
      profileFilter &&
      profileFilter !== "All profiles" &&
      profileFilter !== "Filter by all profiles"
    ) {
      out = out.filter((r) =>
        (r.profile || r.entity || "")
          .toLowerCase()
          .includes(profileFilter.toLowerCase()),
      );
    }
    if (tab === "Outstanding")
      out = out.filter(
        (r) => String(r.status).toLowerCase() === "outstanding",
      );
    if (tab === "Paid")
      out = out.filter((r) => String(r.status).toLowerCase() === "paid");
    if (q) {
      out = out.filter((r) =>
        [
          r.name,
          r.investor,
          r.entity,
          r.status,
          toISODate(r.dueDate),
          toISODate(r.paidDate),
          r.amountDue,
        ]
          .map((x) => (x == null ? "" : String(x)))
          .some((s) => s.toLowerCase().includes(q)),
      );
    }
    out.sort((a, b) => (a._due - b._due) * (dueAsc ? 1 : -1));
    return out;
  }, [rows, profileFilter, tab, query, dueAsc]);

  function onExport() {
    const header = [
      visible.name && "Name",
      visible.investor && "Investor",
      visible.entity && "Entity",
      visible.dueDate && "Due Date",
      visible.status && "Status",
      visible.amountDue && "Amount Due",
      visible.paidDate && "Paid Date",
    ].filter(Boolean);
    const body = filtered.map((r) =>
      [
        visible.name && r.name,
        visible.investor && r.investor,
        visible.entity && r.entity,
        visible.dueDate && toISODate(r.dueDate),
        visible.status && r.status,
        visible.amountDue && r.amountDue,
        visible.paidDate && toISODate(r.paidDate),
      ].filter(Boolean),
    );
    downloadCSV("statements.csv", [header, ...body]);
  }

  const colToggle = (key) =>
    setVisible((v) => ({ ...v, [key]: !v[key] }));

  /* ---------------- actions ---------------- */
  async function onGenerateQuarter() {
    setGenBusy(true);
    setErr("");
    try {
      const payload = {
        year: Number(year),
        quarter: Number(quarter),
        entity_name: entityName,
        ...(effectiveInvestorId ? { investor_id: effectiveInvestorId } : {}),
      };
      await api.post("/api/statements/generate-quarter", payload);
      await fetchRows();
    } catch (e) {
      const msg =
        e?.response?.data?.error || e.message || "Request failed";
      setErr(`POST /api/statements/generate-quarter -> ${msg}`);
    } finally {
      setGenBusy(false);
    }
  }

  // ---- VIEW LOGIC for generated statements (drawer) ----
  async function openDetail(id) {
    setDetailId(id);
    setDetail(null);
    setDetailErr("");
    setPdfErr("");
    setDetailLoading(true);

    // 1) Fetch PDF as blob (auth carried by axios), then create a Blob URL
    try {
      const res = await api.get(`/api/statements/${id}/pdf`, {
        responseType: "blob",
        params: { inline: 1 },
      });
      if (pdfObjectUrlRef.current) {
        URL.revokeObjectURL(pdfObjectUrlRef.current);
      }
      const url = URL.createObjectURL(res.data);
      pdfObjectUrlRef.current = url;
      setPdfUrl(`${url}#toolbar=0`);
    } catch (e) {
      setPdfErr(
        e?.response?.data?.error ||
          e.message ||
          "Failed to load the PDF preview.",
      );
      setPdfUrl("");
    }

    // 2) Fetch JSON detail for the right-hand numbers
    try {
      const { data, headers } = await api.get(`/api/statements/${id}`, {
        headers: { Accept: "application/json" },
      });
      if (typeof data !== "object") {
        const ct = headers?.["content-type"] || "unknown";
        throw new Error(
          `Server did not return JSON (content-type: ${ct}).`,
        );
      }
      setDetail(data);
    } catch (e) {
      setDetailErr(String(e?.response?.data?.error || e.message || e));
    } finally {
      setDetailLoading(false);
    }
  }

  function closeDetail() {
    setDetailId(null);
    setDetail(null);
    setDetailErr("");
    setPdfUrl("");
    setPdfErr("");
    if (pdfObjectUrlRef.current) {
      URL.revokeObjectURL(pdfObjectUrlRef.current);
      pdfObjectUrlRef.current = null;
    }
  }

  // also revoke blob on unmount
  useEffect(() => {
    return () => {
      if (pdfObjectUrlRef.current) {
        URL.revokeObjectURL(pdfObjectUrlRef.current);
        pdfObjectUrlRef.current = null;
      }
    };
  }, []);

  async function onDeleteStatement(row) {
    if (!row?.id) return;
    if (
      !window.confirm(
        `Delete this statement?\n\n${row.name}\nInvestor: ${row.investor}\nEntity: ${row.entity}`,
      )
    )
      return;
    try {
      await api.delete(`/api/statements/${row.id}`);
      setRows((prev) => prev.filter((r) => r.id !== row.id));
    } catch (e) {
      alert(
        `Failed to delete: ${
          e?.response?.data?.error || e.message || e
        }`,
      );
    } finally {
      setOpenActionId(null);
    }
  }

  // ---- VIEW LOGIC for uploaded statement documents (like admin Documents) ----
  async function openDocViewer(doc) {
    setDocViewerOpen(true);
    setDocViewerDoc(doc);
    setDocViewerUrl(null);
    setDocViewerText(null);
    setDocViewerLoading(true);

    try {
      const res = await api.get(`/api/documents/view/${doc.id}`, {
        responseType: "blob",
      });
      const mime =
        res.headers["content-type"] ||
        doc.mime_type ||
        "application/octet-stream";

      if (
        mime.startsWith("text/") ||
        ["csv", "json", "txt", "md"].includes(getExt(doc.original_name))
      ) {
        const text = await res.data.text();
        setDocViewerText(text);
      } else {
        const url = URL.createObjectURL(res.data);
        setDocViewerUrl(url);
      }
    } catch (e) {
      alert("Could not open preview. Try Download.");
    } finally {
      setDocViewerLoading(false);
    }
  }

  function closeDocViewer() {
    setDocViewerOpen(false);
    if (docViewerUrl) {
      URL.revokeObjectURL(docViewerUrl);
    }
    setDocViewerUrl(null);
    setDocViewerText(null);
    setDocViewerDoc(null);
  }

  // cleanup for doc viewer blob URL
  useEffect(() => {
    return () => {
      if (docViewerUrl) {
        URL.revokeObjectURL(docViewerUrl);
      }
    };
  }, [docViewerUrl]);

  // dismiss menus on outside click/scroll/resize
  useEffect(() => {
    const onClick = (e) => {
      if (
        floatingMenuRef.current &&
        floatingMenuRef.current.contains(e.target)
      )
        return;
      if (
        columnsMenuRef.current &&
        !columnsMenuRef.current.contains(e.target)
      )
        setShowColumnsMenu(false);
      if (
        actionsTriggerRef.current &&
        !actionsTriggerRef.current.contains(e.target)
      )
        setOpenActionId(null);
    };
    const onScrollOrResize = () => setOpenActionId(null);
    document.addEventListener("mousedown", onClick);
    window.addEventListener("scroll", onScrollOrResize, true);
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      document.removeEventListener("mousedown", onClick);
      window.removeEventListener("scroll", onScrollOrResize, true);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, []);

  return (
    <div className="space-y-4">
      {/* Top controls removed intentionally (filters/tabs/quarter/refresh) */}

      {/* Search + actions + generated statements table */}
      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by anything"
            className="w-72 max-w-[60%] flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-200"
          />

          <div className="flex items-center gap-2">
            <button
              onClick={onExport}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              title="Export visible rows to CSV"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="opacity-70"
              >
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              Export
            </button>

            {/* Columns menu (desktop) */}
            <div className="relative hidden md:block" ref={columnsMenuRef}>
              <button
                onClick={() => setShowColumnsMenu((v) => !v)}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                title="Show / hide columns"
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="opacity-70"
                >
                  <line x1="4" y1="21" x2="4" y2="14" />
                  <line x1="4" y1="10" x2="4" y2="3" />
                  <line x1="12" y1="21" x2="12" y2="12" />
                  <line x1="12" y1="8" x2="12" y2="3" />
                  <line x1="20" y1="21" x2="20" y2="16" />
                  <line x1="20" y1="12" x2="20" y2="3" />
                  <line x1="1" y1="14" x2="7" y2="14" />
                  <line x1="9" y1="8" x2="15" y2="8" />
                  <line x1="17" y1="16" x2="23" y2="16" />
                </svg>
                Edit columns
              </button>
              {showColumnsMenu && (
                <div className="absolute right-0 z-10 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-2 text-sm shadow-lg">
                  {Object.keys(visible).map((key) => (
                    <label
                      key={key}
                      className="flex items-center justify-between rounded-lg px-2 py-1.5 hover:bg-slate-50"
                    >
                      <span className="capitalize text-slate-700">
                        {key === "dueDate"
                          ? "Due Date"
                          : key === "paidDate"
                          ? "Paid Date"
                          : key === "actions"
                          ? "Actions"
                          : key.charAt(0).toUpperCase() + key.slice(1)}
                      </span>
                      <input
                        type="checkbox"
                        className="h-4 w-4"
                        checked={visible[key]}
                        onChange={() =>
                          setVisible((v) => ({
                            ...v,
                            [key]: !v[key],
                          }))
                        }
                      />
                    </label>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Desktop table */}
        <div className="hidden overflow-x-auto md:block">
          <table className="min-w-full table-fixed">
            <thead>
              <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                {visible.name && (
                  <th className="w-[17%] px-4 py-3">Name</th>
                )}
                {visible.investor && (
                  <th className="w-[17%] px-4 py-3">Investor</th>
                )}
                {visible.entity && (
                  <th className="w-[17%] px-4 py-3">Entity</th>
                )}
                {visible.dueDate && (
                  <th className="w-[12%] px-4 py-3">
                    <button
                      onClick={() => setDueAsc((v) => !v)}
                      className="inline-flex items-center gap-1 text-slate-500 hover:text-slate-700"
                      title="Sort by Due Date"
                    >
                      <span>Due Date</span>
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        {dueAsc ? (
                          <polyline points="6 15 12 9 18 15" />
                        ) : (
                          <polyline points="6 9 12 15 18 9" />
                        )}
                      </svg>
                    </button>
                  </th>
                )}
                {visible.status && (
                  <th className="w-[10%] px-4 py-3">Status</th>
                )}
                {visible.amountDue && (
                  <th className="w-[10%] px-4 py-3">Amount Due</th>
                )}
                {visible.paidDate && (
                  <th className="w-[10%] px-4 py-3">Paid Date</th>
                )}
                {visible.download && (
                  <th className="w-[7%] px-4 py-3">PDF</th>
                )}
                {visible.actions && (
                  <th className="w-[7%] px-4 py-3">Actions</th>
                )}
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100 text-sm">
              {loading && (
                <tr>
                  <td
                    className="px-4 py-10 text-center text-slate-500"
                    colSpan={9}
                  >
                    Loading…
                  </td>
                </tr>
              )}
              {!!err && !loading && (
                <tr>
                  <td
                    className="px-4 py-10 text-center text-rose-600"
                    colSpan={9}
                  >
                    {err}
                  </td>
                </tr>
              )}
              {!loading && !err && filtered.length === 0 && (
                <tr>
                  <td
                    className="px-4 py-12 text-center text-slate-500"
                    colSpan={9}
                  >
                    {me.ready ? "Nothing to display" : "Loading…"}
                  </td>
                </tr>
              )}

              {filtered.map((row) => (
                <tr key={row.id} className="hover:bg-slate-50/60">
                  {visible.name && (
                    <td
                      className="truncate px-4 py-3 font-medium text-slate-800"
                      title={row.name}
                    >
                      {row.name}
                    </td>
                  )}
                  {visible.investor && (
                    <td
                      className="truncate px-4 py-3 text-slate-700"
                      title={row.investor}
                    >
                      {row.investor}
                    </td>
                  )}
                  {visible.entity && (
                    <td
                      className="truncate px-4 py-3 text-slate-700"
                      title={row.entity}
                    >
                      {row.entity}
                    </td>
                  )}
                  {visible.dueDate && (
                    <td className="px-4 py-3 text-slate-700">
                      {toISODate(row.dueDate) || "—"}
                    </td>
                  )}
                  {visible.status && (
                    <td className="px-4 py-3">
                      <span
                        className={cx(
                          "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
                          String(row.status).toLowerCase() === "paid"
                            ? "bg-green-50 text-green-700 ring-1 ring-green-200"
                            : "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
                        )}
                      >
                        {row.status}
                      </span>
                    </td>
                  )}
                  {visible.amountDue && (
                    <td className="px-4 py-3 tabular-nums text-slate-800">
                      {toCurrency(row.amountDue)}
                    </td>
                  )}
                  {visible.paidDate && (
                    <td className="px-4 py-3 text-slate-700">
                      {toISODate(row.paidDate) || "—"}
                    </td>
                  )}
                  {visible.download && (
                    <td className="px-4 py-3">
                      {row.pdfAvailable ? (
                        <a
                          href={`/api/statements/${row.id}/pdf`}
                          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
                        >
                          Download
                        </a>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                  )}
                  {visible.actions && (
                    <td className="px-4 py-3" ref={actionsTriggerRef}>
                      <button
                        onClick={(e) => {
                          const r =
                            e.currentTarget.getBoundingClientRect();
                          setMenuPos({
                            top: r.bottom + 8,
                            left: Math.max(8, r.right - 144),
                          });
                          setOpenActionId((cur) =>
                            cur === row.id ? null : row.id,
                          );
                        }}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                        title="Actions"
                      >
                        <svg
                          width="18"
                          height="18"
                          viewBox="0 0 24 24"
                          fill="currentColor"
                        >
                          <circle cx="12" cy="5" r="2" />
                          <circle cx="12" cy="12" r="2" />
                          <circle cx="12" cy="19" r="2" />
                        </svg>
                      </button>

                      {openActionId === row.id &&
                        createPortal(
                          <div
                            ref={floatingMenuRef}
                            style={{
                              position: "fixed",
                              top: menuPos.top,
                              left: menuPos.left,
                              zIndex: 1000,
                            }}
                            className="w-36 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg"
                          >
                            <button
                              onClick={() => {
                                setOpenActionId(null);
                                openDetail(row.id);
                              }}
                              className="block w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                            >
                              View
                            </button>
                            <button
                              onClick={() => onDeleteStatement(row)}
                              className="block w-full px-3 py-2 text-left text-sm text-rose-600 hover:bg-rose-50"
                            >
                              Delete
                            </button>
                          </div>,
                          document.body,
                        )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Mobile list */}
        <div className="md:hidden">
          {loading && (
            <div className="px-4 py-8 text-center text-slate-500">
              Loading…
            </div>
          )}
          {!!err && !loading && (
            <div className="px-4 py-8 text-center text-rose-600">
              {err}
            </div>
          )}
          {!loading && !err && filtered.length === 0 && (
            <div className="px-4 py-12 text-center text-slate-500">
              {me.ready ? "Nothing to display" : "Loading…"}
            </div>
          )}

          <ul className="divide-y divide-slate-100">
            {filtered.map((row) => (
              <li key={row.id} className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-slate-900">
                      {row.name}
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      {row.investor} • {row.entity}
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {row.pdfAvailable ? (
                      <a
                        href={`/api/statements/${row.id}/pdf`}
                        className="rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50"
                      >
                        PDF
                      </a>
                    ) : null}

                    <button
                      onClick={(e) => {
                        const r =
                          e.currentTarget.getBoundingClientRect();
                        setMenuPos({
                          top: r.bottom + 8,
                          left: Math.max(8, r.right - 144),
                        });
                        setOpenActionId((cur) =>
                          cur === row.id ? null : row.id,
                        );
                      }}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                      title="Actions"
                      ref={actionsTriggerRef}
                    >
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="currentColor"
                      >
                        <circle cx="12" cy="5" r="2" />
                        <circle cx="12" cy="12" r="2" />
                        <circle cx="12" cy="19" r="2" />
                      </svg>
                    </button>
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-lg bg-slate-50 px-3 py-2">
                    <div className="text-xs text-slate-500">Due</div>
                    <div className="text-slate-800">
                      {toISODate(row.dueDate) || "—"}
                    </div>
                  </div>
                  <div className="rounded-lg bg-slate-50 px-3 py-2">
                    <div className="text-xs text-slate-500">Amount</div>
                    <div className="tabular-nums text-slate-800">
                      {toCurrency(row.amountDue)}
                    </div>
                  </div>
                  <div className="rounded-lg bg-slate-50 px-3 py-2">
                    <div className="text-xs text-slate-500">Status</div>
                    <div
                      className={cx(
                        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
                        String(row.status).toLowerCase() === "paid"
                          ? "bg-green-50 text-green-700 ring-1 ring-green-200"
                          : "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
                      )}
                    >
                      {row.status}
                    </div>
                  </div>
                  <div className="rounded-lg bg-slate-50 px-3 py-2">
                    <div className="text-xs text-slate-500">Paid</div>
                    <div className="text-slate-800">
                      {toISODate(row.paidDate) || "—"}
                    </div>
                  </div>
                </div>

                {openActionId === row.id &&
                  createPortal(
                    <div
                      ref={floatingMenuRef}
                      style={{
                        position: "fixed",
                        top: menuPos.top,
                        left: menuPos.left,
                        zIndex: 1000,
                      }}
                      className="w-36 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg"
                    >
                      <button
                        onClick={() => {
                          setOpenActionId(null);
                          openDetail(row.id);
                        }}
                        className="block w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                      >
                        View
                      </button>
                      <button
                        onClick={() => onDeleteStatement(row)}
                        className="block w-full px-3 py-2 text-left text-sm text-rose-600 hover:bg-rose-50"
                      >
                        Delete
                      </button>
                    </div>,
                    document.body,
                  )}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Uploaded statement documents (from /api/documents?share_type=statement) */}
      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-800">
            Uploaded statements (shared files)
          </h3>
          {docsLoading && (
            <span className="text-xs text-slate-500">Loading…</span>
          )}
        </div>
        <div className="px-4 py-3">
          {docsErr && (
            <div className="text-sm text-rose-600">{docsErr}</div>
          )}
          {!docsErr && !docsLoading && statementDocs.length === 0 && (
            <div className="text-sm text-slate-500">
              No uploaded statements have been shared with you yet.
            </div>
          )}
          {!docsErr && statementDocs.length > 0 && (
            <div className="overflow-x-auto">
              <table className="min-w-full table-fixed text-sm">
                <thead>
                  <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="w-[55%] px-2 py-2">Name</th>
                    <th className="w-[25%] px-2 py-2">Uploaded</th>
                    <th className="w-[20%] px-2 py-2">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {statementDocs.map((doc) => (
                    <tr
                      key={doc.id}
                      className="hover:bg-slate-50/60"
                    >
                      <td
                        className="truncate px-2 py-2 font-medium text-slate-800"
                        title={doc.title || doc.original_name}
                      >
                        {doc.title || doc.original_name}
                      </td>
                      <td className="px-2 py-2 text-slate-700">
                        {toISODate(doc.uploaded_at)}
                      </td>
                      <td className="px-2 py-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
                            onClick={() => openDocViewer(doc)}
                          >
                            View
                          </button>
                          <a
                            href={`/api/documents/download/${doc.id}`}
                            className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
                          >
                            Download
                          </a>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Document viewer modal for uploaded statement files (same style as admin Documents) */}
      {docViewerOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 flex items-center justify-center"
          onMouseDown={closeDocViewer}
        >
          <div
            className="bg-white w-[92vw] max-w-5xl max-h-[85vh] rounded-2xl shadow-2xl overflow-hidden"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b">
              <div className="font-semibold text-gray-800 truncate">
                {docViewerDoc?.title || docViewerDoc?.original_name}
              </div>
              <div className="flex items-center gap-3">
                {docViewerDoc && (
                  <a
                    className="text-blue-600 hover:underline"
                    href={`/api/documents/download/${docViewerDoc.id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Download
                  </a>
                )}
                <button
                  className="p-2 rounded hover:bg-slate-100"
                  onClick={closeDocViewer}
                  aria-label="Close"
                >
                  <IoClose size={18} />
                </button>
              </div>
            </div>
            <div className="p-0 bg-slate-50 h-[75vh] overflow-hidden">
              {docViewerLoading && (
                <div className="h-full grid place-items-center text-sm text-slate-600">
                  Loading preview…
                </div>
              )}

              {!docViewerLoading &&
                docViewerUrl &&
                (docViewerDoc?.mime_type || "").includes("pdf") && (
                  <iframe
                    title="File preview"
                    src={docViewerUrl}
                    className="w-full h-full"
                  />
                )}

              {!docViewerLoading &&
                docViewerUrl &&
                docViewerDoc &&
                docViewerDoc.mime_type &&
                docViewerDoc.mime_type.startsWith("image/") && (
                  <img
                    src={docViewerUrl}
                    alt="preview"
                    className="max-h-full max-w-full object-contain mx-auto"
                  />
                )}

              {!docViewerLoading && docViewerText && (
                <pre className="h-full overflow-auto p-4 whitespace-pre-wrap text-[13px] leading-5">
                  {docViewerText}
                </pre>
              )}

              {!docViewerLoading &&
                !docViewerUrl &&
                !docViewerText && (
                  <div className="h-full grid place-items-center text-sm text-slate-600">
                    No preview available. Use Download instead.
                  </div>
                )}
            </div>
          </div>
        </div>
      )}

      {/* Drawer for generated statements */}
      {detailId !== null && (
        <div className="fixed inset-0 z-30">
          <div
            className="absolute inset-0 bg-black/20"
            onClick={closeDetail}
          />
          <div className="absolute right-0 top-0 h-full w-full max-w-[920px] overflow-y-auto rounded-l-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <div>
                <div className="text-sm text-slate-500">
                  {detail?.entity} &middot; {detail?.investor}
                </div>
                <div className="text-base font-semibold text-slate-900">
                  Statement {detail?.period?.start} –{" "}
                  {detail?.period?.end}
                </div>
              </div>
              <button
                onClick={closeDetail}
                className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50"
              >
                Close
              </button>
            </div>

            <div className="p-5">
              {/* PDF preview */}
              <div className="mb-4 rounded-xl border border-slate-200 bg-slate-50">
                {pdfUrl ? (
                  <iframe
                    key={detailId}
                    title="Statement PDF preview"
                    src={pdfUrl}
                    style={{
                      width: "100%",
                      height: "72vh",
                      border: 0,
                    }}
                    onError={() =>
                      setPdfErr("Failed to load the PDF preview.")
                    }
                  />
                ) : null}
              </div>
              {pdfErr && (
                <div className="mb-4 text-center text-sm text-rose-600">
                  {pdfErr}{" "}
                  {detailId ? (
                    <a
                      className="underline"
                      href={`/api/statements/${detailId}/pdf`}
                    >
                      Download instead
                    </a>
                  ) : null}
                </div>
              )}

              {/* Numeric detail – left as-is (your server defines this) */}
              {detailLoading && (
                <div className="py-10 text-center text-slate-500">
                  Loading…
                </div>
              )}
              {!!detailErr && (
                <div className="whitespace-pre-wrap py-10 text-center text-rose-600">
                  {detailErr}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- small sub-tables ---------- */
function Row({ label, value, fmt = "money" }) {
  const out = fmt === "pct" ? toPct(value, 4) : toCurrency(value);
  return (
    <div className="grid grid-cols-[1fr_auto] items-center gap-3 py-1.5 text-sm">
      <div className="text-slate-600">{label}</div>
      <div
        className={cx(
          "tabular-nums font-medium",
          fmt === "pct" ? "text-slate-800" : "text-slate-900",
        )}
      >
        {out}
      </div>
    </div>
  );
}
