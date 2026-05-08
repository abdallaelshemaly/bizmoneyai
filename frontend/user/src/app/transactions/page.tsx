"use client";

import { isAxiosError } from "axios";
import { useEffect, useRef, useState } from "react";

import Navbar from "@/components/Navbar";
import { useAuth } from "@/hooks/useAuth";
import api from "@/lib/api";

type Cat = { category_id: number; name: string; type: string };
type FraudRiskLevel = "warning" | "critical";
type Tx = {
  transaction_id: number;
  category_id: number;
  amount: number;
  type: "income" | "expense";
  description: string | null;
  date: string;
  fraud_risk_level: FraudRiskLevel | null;
  fraud_probability: number | null;
  fraud_insight_id: number | null;
};
type Sug = { suggested_category_id: number | null; suggested_category_name: string | null; confidence: number };
type UnusualDetection = { fraud_probability: number | null; risk_level: FraudRiskLevel };
type FormState = { category_id: string; amount: string; type: "income" | "expense"; description: string; date: string };
type ImportResult = { imported_count: number; skipped_count: number; rejected_rows: { row_number: number; reason: string }[]; transactions: Tx[] };

const EMPTY: FormState = {
  category_id: "",
  amount: "",
  type: "expense",
  description: "",
  date: new Date().toISOString().slice(0, 10),
};
const RISK_BADGE = {
  warning: "bg-yellow-100 text-yellow-800",
  critical: "bg-red-100 text-red-700",
};

export default function TransactionsPage() {
  const { user, loading } = useAuth();
  const [cats, setCats] = useState<Cat[]>([]);
  const [txs, setTxs] = useState<Tx[]>([]);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [editId, setEditId] = useState<number | null>(null);
  const [sug, setSug] = useState<Sug | null>(null);
  const [unusualDetection, setUnusualDetection] = useState<UnusualDetection | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [fType, setFType] = useState("");
  const [fCat, setFCat] = useState("");
  const [fDateFrom, setFDateFrom] = useState("");
  const [fDateTo, setFDateTo] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const tmrRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = async (type = fType, cat = fCat, dateFrom = fDateFrom, dateTo = fDateTo) => {
    const p = new URLSearchParams();
    if (type) p.set("type", type);
    if (cat) p.set("category_id", cat);
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    const [cr, tr] = await Promise.all([api.get<Cat[]>("/categories"), api.get<Tx[]>(`/transactions?${p}`)]);
    setCats(cr.data);
    setTxs(tr.data);
  };

  useEffect(() => {
    if (!user) return;
    load();
  }, [user, fType, fCat, fDateFrom, fDateTo]); // eslint-disable-line react-hooks/exhaustive-deps

  const predict = async (text: string) => {
    if (text.trim().length < 3) return;
    try {
      const r = await api.post<Sug>("/ml/predict-category", { text });
      setSug(r.data);
      if (r.data.suggested_category_id && !form.category_id) {
        setForm((current) => ({ ...current, category_id: String(r.data.suggested_category_id) }));
      }
    } catch {}
  };

  const onDesc = (value: string) => {
    setForm((current) => ({ ...current, description: value }));
    if (tmrRef.current) clearTimeout(tmrRef.current);
    tmrRef.current = setTimeout(() => predict(value), 600);
  };

  const startEdit = (tx: Tx) => {
    setEditId(tx.transaction_id);
    setForm({
      category_id: String(tx.category_id),
      amount: String(tx.amount),
      type: tx.type,
      description: tx.description ?? "",
      date: tx.date,
    });
    setSug(null);
    setUnusualDetection(null);
  };

  const cancel = () => {
    setEditId(null);
    setForm(EMPTY);
    setSug(null);
    setUnusualDetection(null);
    setError("");
  };

  const save = async () => {
    if (!form.category_id || !form.amount) {
      setError("Category and amount are required.");
      return;
    }
    setError("");
    setNotice("");
    setUnusualDetection(null);
    setBusy(true);
    const body = {
      category_id: Number(form.category_id),
      amount: parseFloat(form.amount),
      type: form.type,
      description: form.description || null,
      date: form.date,
    };
    try {
      if (editId !== null) {
        await api.put(`/transactions/${editId}`, body);
      } else {
        const response = await api.post<Tx>("/transactions", body);
        setUnusualDetection(
          response.data.fraud_risk_level
            ? {
                risk_level: response.data.fraud_risk_level,
                fraud_probability: response.data.fraud_probability,
              }
            : null,
        );
      }
      setForm(EMPTY);
      setEditId(null);
      setSug(null);
      await load();
    } catch (error: unknown) {
      const detail = isAxiosError(error) ? error.response?.data?.detail : null;
      if (typeof detail === "string") {
        setError(detail);
      } else if (Array.isArray(detail) && typeof detail[0]?.msg === "string") {
        setError(detail[0].msg);
      } else {
        setError("Failed to save.");
      }
    } finally {
      setBusy(false);
    }
  };

  const del = async (id: number) => {
    if (!confirm("Delete?")) return;
    await api.delete(`/transactions/${id}`);
    await load();
  };

  const exportCsv = async () => {
    const r = await api.get("/transactions/export-csv", { responseType: "blob" });
    const url = URL.createObjectURL(new Blob([r.data as BlobPart]));
    const a = document.createElement("a");
    a.href = url;
    a.download = "transactions.csv";
    a.click();
  };

  const exportExcel = async () => {
    const r = await api.get("/transactions/export-excel", { responseType: "blob" });
    const url = URL.createObjectURL(new Blob([r.data as BlobPart]));
    const a = document.createElement("a");
    a.href = url;
    a.download = "transactions.xlsx";
    a.click();
  };

  const importFile = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    setError("");
    setNotice("");
    try {
      const response = await api.post<ImportResult>("/transactions/import-file", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      await load();
      const { imported_count, skipped_count } = response.data;
      const unusualCount = response.data.transactions.filter((tx) => tx.fraud_risk_level).length;
      setNotice(
        skipped_count > 0
          ? `Imported ${imported_count} transactions. Skipped ${skipped_count} duplicate row${skipped_count === 1 ? "" : "s"}.${unusualCount ? ` Flagged ${unusualCount} unusual transaction${unusualCount === 1 ? "" : "s"}.` : ""}`
          : `Imported ${imported_count} transactions.${unusualCount ? ` Flagged ${unusualCount} unusual transaction${unusualCount === 1 ? "" : "s"}.` : ""}`,
      );
    } catch (error: unknown) {
      const detail = isAxiosError(error) ? error.response?.data?.detail : null;
      setError(
        typeof detail === "string"
          ? detail
            : Array.isArray(detail) && typeof detail[0]?.msg === "string"
              ? detail[0].msg
            : "File import failed.",
      );
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const resetFilters = () => {
    setFType("");
    setFCat("");
    setFDateFrom("");
    setFDateTo("");
  };

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center text-slate-400">Loading...</div>;
  }

  const cName = (id: number) => cats.find((c) => c.category_id === id)?.name ?? "-";

  return (
    <>
      <Navbar userName={user?.name} />
      <main className="mx-auto max-w-6xl space-y-8 p-6">
        <h1 className="text-3xl font-bold text-ink">Transactions</h1>
        {error && <div className="rounded bg-red-100 px-4 py-2 text-sm text-red-700">{error}</div>}
        {notice && <div className="rounded bg-green-100 px-4 py-2 text-sm text-green-700">{notice}</div>}
        {unusualDetection && (
          <div
            className={`rounded px-4 py-2 text-sm ${
              unusualDetection.risk_level === "critical"
                ? "bg-red-100 text-red-700"
                : "bg-yellow-100 text-yellow-800"
            }`}
          >
            {unusualDetection.risk_level === "critical"
              ? "Critical unusual transaction detected. Review this transaction immediately."
              : "Unusual transaction detected. This transaction appears higher risk than normal."}
            {unusualDetection.fraud_probability !== null && (
              <span className="ml-2 font-medium">
                {Math.round(unusualDetection.fraud_probability * 100)}% risk
              </span>
            )}
          </div>
        )}

        <div className="rounded-xl bg-white p-6 shadow">
          <h2 className="mb-4 font-semibold">{editId !== null ? "Edit Transaction" : "Add New Transaction"}</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs text-slate-500">
                Description <span className="text-slate-400">(AI suggestion)</span>
              </label>
              <input
                placeholder="e.g. Office rent, Client invoice..."
                value={form.description}
                onChange={(e) => onDesc(e.target.value)}
                className="w-full"
              />
              {sug?.suggested_category_name && (
                <p className="mt-1 text-xs text-slate-400">
                  Suggested: <strong className="text-ink">{sug.suggested_category_name}</strong> ({Math.round(sug.confidence * 100)}%)
                </p>
              )}
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">Category *</label>
              <select value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })} className="w-full">
                <option value="">Select category</option>
                {cats.map((c) => (
                  <option key={c.category_id} value={c.category_id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">Amount *</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                placeholder="0.00"
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
                className="w-full"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">Type</label>
              <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as "income" | "expense" })} className="w-full">
                <option value="income">Income</option>
                <option value="expense">Expense</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-500">Date</label>
              <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className="w-full" />
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <button onClick={save} disabled={busy}>{editId !== null ? "Update" : "Add Transaction"}</button>
            {editId !== null && <button onClick={cancel} className="bg-slate-500">Cancel</button>}
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-slate-500">Filter by type</label>
            <select value={fType} onChange={(e) => setFType(e.target.value)} className="text-sm">
              <option value="">All types</option>
              <option value="income">Income</option>
              <option value="expense">Expense</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">Filter by category</label>
            <select value={fCat} onChange={(e) => setFCat(e.target.value)} className="text-sm">
              <option value="">All categories</option>
              {cats.map((c) => (
                <option key={c.category_id} value={c.category_id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">Date from</label>
            <input type="date" value={fDateFrom} onChange={(e) => setFDateFrom(e.target.value)} className="text-sm" />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">Date to</label>
            <input type="date" value={fDateTo} onChange={(e) => setFDateTo(e.target.value)} className="text-sm" />
          </div>
          <button type="button" onClick={resetFilters} className="bg-slate-200 text-sm text-slate-700 hover:bg-slate-300">
            Clear Filters
          </button>
          <button type="button" onClick={exportCsv} className="bg-slate-600 text-sm">Export CSV</button>
          <button type="button" onClick={exportExcel} className="bg-slate-700 text-sm">Export Excel</button>
          <label className="cursor-pointer rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
            Import File
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) importFile(file);
              }}
            />
          </label>
        </div>

        <div className="overflow-x-auto rounded-xl bg-white shadow">
          {txs.length === 0 ? (
            <p className="p-8 text-center text-sm text-slate-400">No transactions found.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left">Date</th>
                  <th className="px-4 py-3 text-left">Category</th>
                  <th className="px-4 py-3 text-left">Description</th>
                  <th className="px-4 py-3 text-left">Type</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                  <th className="px-4 py-3 text-left">Risk</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {txs.map((tx, i) => (
                  <tr key={tx.transaction_id} className={i % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                    <td className="px-4 py-3 text-slate-500">{tx.date}</td>
                    <td className="px-4 py-3 font-medium">{cName(tx.category_id)}</td>
                    <td className="px-4 py-3 text-slate-500">{tx.description || "-"}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${tx.type === "income" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                        {tx.type}
                      </span>
                    </td>
                    <td className={`px-4 py-3 text-right font-semibold ${tx.type === "income" ? "text-green-600" : "text-red-500"}`}>
                      {tx.type === "income" ? "+" : "-"}${Number(tx.amount).toFixed(2)}
                    </td>
                    <td className="px-4 py-3">
                      {tx.fraud_risk_level ? (
                        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${RISK_BADGE[tx.fraud_risk_level]}`}>
                          {tx.fraud_risk_level === "critical" ? "Critical" : "Unusual"}
                          {tx.fraud_probability !== null ? ` ${Math.round(tx.fraud_probability * 100)}%` : ""}
                        </span>
                      ) : (
                        <span className="text-xs text-slate-400">No alert</span>
                      )}
                    </td>
                    <td className="px-4 py-3 space-x-2 text-right">
                      <button onClick={() => startEdit(tx)} className="bg-slate-700 px-3 py-1 text-xs">Edit</button>
                      <button onClick={() => del(tx.transaction_id)} className="bg-red-600 px-3 py-1 text-xs">Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>
    </>
  );
}
