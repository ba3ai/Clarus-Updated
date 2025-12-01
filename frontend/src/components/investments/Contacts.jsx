import React, { useEffect, useMemo, useRef, useState } from "react";
import api from "../../services/api";

/**
 * Contacts.jsx
 * - Cookie + CSRF auth via shared axios `api` (same as Documents.jsx)
 * - Server-side search
 * - Add / Edit / Delete contacts
 * - Export CSV
 * - Hide/show columns
 * - Action column with 3-dot menu (Edit / Delete)
 */

const DEFAULT_COLUMNS = [
  { key: "name", label: "NAME", visible: true },
  { key: "email", label: "EMAIL", visible: true },
  { key: "phone", label: "PHONE", visible: true },
  { key: "notes", label: "NOTES", visible: true },
];

function resolveInvestorId() {
  try {
    const url = new URL(window.location.href);
    const fromQuery = url.searchParams.get("investorId");
    const fromStorage = localStorage.getItem("currentInvestorId");
    return Number(fromQuery || fromStorage || 1);
  } catch {
    return 1;
  }
}

export default function Contacts() {
  const investorId = resolveInvestorId();

  const [contacts, setContacts] = useState([]);
  const [query, setQuery] = useState("");
  const [columns, setColumns] = useState(DEFAULT_COLUMNS);
  const [menuOpen, setMenuOpen] = useState(false);

  const [showModal, setShowModal] = useState(false);
  const [modalMode, setModalMode] = useState("add"); // "add" | "edit"
  const [editingContact, setEditingContact] = useState(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Debounced server-side load on query change
  useEffect(() => {
    let cancelled = false;
    const handle = setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const res = await api.get(`/api/contacts/${investorId}`, {
          params: {
            q: query,
            page: 1,
            page_size: 200,
          },
        });
        const data = res.data;
        if (!cancelled) {
          setContacts(Array.isArray(data?.data) ? data.data : []);
        }
      } catch (e) {
        if (!cancelled) {
          const msg =
            e?.response?.data?.error ||
            e?.message ||
            "Failed to load contacts.";
          setError(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 300);

    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [investorId, query]);

  const visibleCols = useMemo(
    () => columns.filter((c) => c.visible),
    [columns]
  );

  function toggleColumn(key) {
    setColumns((prev) =>
      prev.map((c) => (c.key === key ? { ...c, visible: !c.visible } : c))
    );
  }

  function exportCSV() {
    const cols = visibleCols;
    const header = cols.map((c) => c.label).join(",");
    const lines = contacts.map((row) =>
      cols
        .map((c) => {
          const val = row[c.key] ?? "";
          const escaped = String(val).replaceAll('"', '""');
          return `"${escaped}"`;
        })
        .join(",")
    );
    const csv = [header, ...lines].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "contacts.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleDelete(contactId) {
    if (!contactId) return;
    if (!window.confirm("Are you sure you want to delete this contact?")) {
      return;
    }
    try {
      await api.delete(`/api/contacts/item/${contactId}`);
      setContacts((prev) => prev.filter((c) => c.id !== contactId));
    } catch (e) {
      const msg =
        e?.response?.data?.error ||
        e?.message ||
        "Failed to delete contact.";
      setError(msg);
    }
  }

  function openAddModal() {
    setModalMode("add");
    setEditingContact(null);
    setShowModal(true);
  }

  function openEditModal(contact) {
    setModalMode("edit");
    setEditingContact(contact);
    setShowModal(true);
  }

  return (
    <div className="w-full">
      {/* Header bar */}
      <div className="flex items-center justify-between gap-3 py-4">
        <div className="flex-1 max-w-sm">
          <div className="relative">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by anything"
              className="w-full rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm outline-none ring-0 placeholder:text-gray-400 focus:border-gray-300 focus:ring-2 focus:ring-gray-100"
            />
            <svg
              viewBox="0 0 24 24"
              className="pointer-events-none absolute right-3 top-1/2 h-5 w-5 -translate-y-1/2 opacity-50"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M21 21l-4.3-4.3" />
              <circle cx="10" cy="10" r="7" />
            </svg>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Export */}
          <button
            onClick={exportCSV}
            className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium hover:bg-gray-50 active:scale-[.99]"
            title="Export CSV"
          >
            Export
          </button>

          {/* Hide Columns menu */}
          <div className="relative">
            <button
              onClick={() => setMenuOpen((s) => !s)}
              className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium hover:bg-gray-50 active:scale-[.99]"
              title="Show / hide columns"
            >
              Hide columns
            </button>
            {menuOpen && (
              <div
                className="absolute right-0 z-20 mt-2 w-56 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-lg"
                onMouseLeave={() => setMenuOpen(false)}
              >
                <div className="p-2 text-xs font-semibold text-gray-500">
                  Columns
                </div>
                <div className="max-h-64 overflow-auto p-2">
                  {columns.map((c) => (
                    <label
                      key={c.key}
                      className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 text-sm hover:bg-gray-50"
                    >
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded"
                        checked={c.visible}
                        onChange={() => toggleColumn(c.key)}
                      />
                      <span>{c.label}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Add Contact */}
          <button
            onClick={openAddModal}
            className="inline-flex items-center gap-2 rounded-xl bg-[#2B86C5] px-4 py-2 text-sm font-semibold text-white shadow-sm hover:brightness-110 active:scale-[.99]"
          >
            <span className="inline-flex h-5 w-5 items-center justify-center rounded-md bg-white/20">
              +
            </span>
            Add Contact
          </button>
        </div>
      </div>

      {/* Table / Empty state card */}
      <div className="rounded-2xl border border-gray-200 bg-white">
        {/* header row */}
        <div className="grid grid-cols-5 gap-4 border-b border-gray-100 px-5 py-3 text-xs font-semibold tracking-wide text-gray-500">
          {visibleCols.map((c) => (
            <div key={c.key}>{c.label}</div>
          ))}
          <div className="text-right">Action</div>
        </div>

        {/* Body */}
        {loading ? (
          <div className="flex min-h-[220px] items-center justify-center p-8">
            <span className="text-sm text-gray-500">Loading…</span>
          </div>
        ) : error ? (
          <div className="flex min-h-[220px] items-center justify-center p-8">
            <span className="text-sm text-red-500">{error}</span>
          </div>
        ) : contacts.length > 0 ? (
          <div className="divide-y divide-gray-100">
            {contacts.map((row) => (
              <div
                key={row.id ?? `${row.name}-${row.email}`}
                className="grid grid-cols-5 gap-4 px-5 py-4 text-sm"
              >
                {visibleCols.map((c) => (
                  <div key={c.key}>
                    {row[c.key] || <span className="text-gray-400">—</span>}
                  </div>
                ))}

                {/* ACTION column */}
                <div className="flex items-center justify-end">
                  <RowActions
                    onEdit={() => openEditModal(row)}
                    onDelete={() => handleDelete(row.id)}
                  />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex min-h-[260px] flex-col items-center justify-center gap-2 px-6 py-16 text-center">
            <p className="max-w-2xl text-base font-semibold text-gray-700">
              Please add anyone here you would like copied on correspondence
              such as emails and invoices.
            </p>
            <p className="text-sm text-gray-400">Nothing to display</p>
          </div>
        )}
      </div>

      {/* Add / Edit Contact Modal */}
      {showModal && (
        <ContactModal
          mode={modalMode}
          investorId={investorId}
          contactId={editingContact?.id}
          initial={editingContact}
          onClose={() => {
            setShowModal(false);
            setEditingContact(null);
          }}
          onSaved={(saved, mode) => {
            if (saved) {
              setContacts((prev) => {
                if (mode === "edit") {
                  return prev.map((c) => (c.id === saved.id ? saved : c));
                }
                return [saved, ...prev];
              });
            }
            setShowModal(false);
            setEditingContact(null);
          }}
        />
      )}
    </div>
  );
}

/* 3-dot actions menu */
function RowActions({ onEdit, onDelete }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handleClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 w-8 items-center justify-center rounded-full hover:bg-gray-100 text-gray-600"
        title="Actions"
      >
        {/* 3 vertical dots */}
        <svg
          viewBox="0 0 24 24"
          className="h-5 w-5"
          fill="currentColor"
          aria-hidden="true"
        >
          <circle cx="12" cy="5" r="1.6" />
          <circle cx="12" cy="12" r="1.6" />
          <circle cx="12" cy="19" r="1.6" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 z-30 mt-1 w-32 rounded-lg border border-gray-200 bg-white py-1 text-sm shadow-lg">
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              onEdit?.();
            }}
            className="flex w-full items-center px-3 py-1.5 text-left hover:bg-gray-50"
          >
            Edit
          </button>
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              onDelete?.();
            }}
            className="flex w-full items-center px-3 py-1.5 text-left text-red-600 hover:bg-red-50"
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

/* Modal for both Add + Edit */
function ContactModal({
  mode = "add",
  investorId,
  contactId,
  initial,
  onClose,
  onSaved,
}) {
  const [form, setForm] = useState({
    name: initial?.name || "",
    email: initial?.email || "",
    phone: initial?.phone || "",
    notes: initial?.notes || "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setForm({
      name: initial?.name || "",
      email: initial?.email || "",
      phone: initial?.phone || "",
      notes: initial?.notes || "",
    });
  }, [initial, mode]);

  async function handleSave() {
    if (!form.name.trim() || !form.email.trim()) {
      setError("Name and Email are required.");
      return;
    }
    setSaving(true);
    setError("");

    try {
      let res;
      if (mode === "edit" && contactId) {
        res = await api.put(`/api/contacts/item/${contactId}`, {
          name: form.name.trim(),
          email: form.email.trim(),
          phone: form.phone.trim() || null,
          notes: form.notes.trim() || null,
        });
      } else {
        res = await api.post(`/api/contacts/${investorId}`, {
          name: form.name.trim(),
          email: form.email.trim(),
          phone: form.phone.trim() || null,
          notes: form.notes.trim() || null,
        });
      }
      const data = res.data;
      onSaved?.(data?.data || null, mode);
    } catch (e) {
      const msg =
        e?.response?.data?.error ||
        e?.message ||
        "Failed to save contact.";
      setError(msg);
    } finally {
      setSaving(false);
    }
  }

  const title = mode === "edit" ? "Edit Contact" : "Add Contact";
  const primaryLabel = mode === "edit" ? "Save Changes" : "Save Contact";

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/30 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div className="relative z-50 w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">{title}</h3>
          <button
            className="rounded-lg p-2 text-gray-500 hover:bg-gray-50"
            onClick={onClose}
            aria-label="Close"
            title="Close"
          >
            ✕
          </button>
        </div>

        <div className="grid grid-cols-1 gap-4">
          <Field
            label="Name"
            value={form.name}
            onChange={(v) => setForm((s) => ({ ...s, name: v }))}
            placeholder="Jane Cooper"
            required
          />
          <Field
            label="Email"
            type="email"
            value={form.email}
            onChange={(v) => setForm((s) => ({ ...s, email: v }))}
            placeholder="jane@example.com"
            required
          />
          <Field
            label="Phone"
            value={form.phone}
            onChange={(v) => setForm((s) => ({ ...s, phone: v }))}
            placeholder="+1 555 0123"
          />
          <Field
            label="Notes"
            as="textarea"
            value={form.notes}
            onChange={(v) => setForm((s) => ({ ...s, notes: v }))}
            placeholder="Optional notes…"
          />
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium hover:bg-gray-50"
            disabled={saving}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="rounded-xl bg-[#2B86C5] px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
            disabled={saving}
          >
            {saving ? "Saving…" : primaryLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  as = "input",
  type = "text",
  required = false,
}) {
  const InputTag = as;
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-gray-700">
        {label} {required && <span className="text-red-500">*</span>}
      </span>
      <InputTag
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`w-full rounded-xl border border-gray-200 bg-white px-3 py-2 outline-none ring-0 placeholder:text-gray-400 focus:border-gray-300 focus:ring-2 focus:ring-gray-100 ${
          as === "textarea" ? "min-h-[88px]" : ""
        }`}
      />
    </label>
  );
}
