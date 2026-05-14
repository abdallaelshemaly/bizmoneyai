"use client";

import { isAxiosError } from "axios";
import { useEffect, useState } from "react";

import BizMoneyLoader from "@/components/BizMoneyLoader";
import Navbar from "@/components/Navbar";
import { useAuth } from "@/hooks/useAuth";
import api from "@/lib/api";

type Category = { category_id: number; name: string; type: "income" | "expense" | "both"; created_at: string };
type Form = { name: string; type: "income" | "expense" | "both" };

const EMPTY: Form = { name: "", type: "expense" };
const TS = {
  income: "bg-green-100 text-green-700",
  expense: "bg-red-100 text-red-700",
  both: "bg-blue-100 text-blue-700",
};

export default function CategoriesPage() {
  const { user, loading } = useAuth();
  const [cats, setCats] = useState<Category[]>([]);
  const [initialCategoriesLoading, setInitialCategoriesLoading] = useState(true);
  const [form, setForm] = useState<Form>(EMPTY);
  const [editId, setEditId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = async () => {
    try {
      const r = await api.get<Category[]>("/categories");
      setCats(r.data);
    } finally {
      setInitialCategoriesLoading(false);
    }
  };

  useEffect(() => {
    if (!user) return;
    refresh();
  }, [user]);

  const startEdit = (c: Category) => {
    setEditId(c.category_id);
    setForm({ name: c.name, type: c.type });
  };

  const cancel = () => {
    setEditId(null);
    setForm(EMPTY);
    setError("");
  };

  const save = async () => {
    if (!form.name.trim()) {
      setError("Name is required.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      if (editId !== null) {
        await api.put(`/categories/${editId}`, form);
      } else {
        await api.post("/categories", form);
      }
      setForm(EMPTY);
      setEditId(null);
      await refresh();
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
    if (!confirm("Delete this category?")) return;
    try {
      await api.delete(`/categories/${id}`);
      await refresh();
    } catch {
      setError("Cannot delete - category has linked transactions.");
    }
  };

  if (loading || initialCategoriesLoading) {
    return <BizMoneyLoader fullScreen />;
  }

  return (
    <>
      <Navbar userName={user?.name} />
      <main className="mx-auto max-w-4xl space-y-8 p-6">
        <h1 className="text-3xl font-bold text-ink">Categories</h1>
        {error && <div className="rounded bg-red-100 px-4 py-2 text-sm text-red-700">{error}</div>}
        <div className="rounded-xl bg-white p-6 shadow">
          <h2 className="mb-4 font-semibold">{editId !== null ? "Edit Category" : "Add New Category"}</h2>
          <div className="flex flex-wrap gap-3">
            <input
              placeholder="Category name"
              className="min-w-[160px] flex-1"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              onKeyDown={(e) => e.key === "Enter" && save()}
            />
            <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as Form["type"] })}>
              <option value="income">Income</option>
              <option value="expense">Expense</option>
              <option value="both">Both</option>
            </select>
            <button onClick={save} disabled={busy}>{editId !== null ? "Update" : "Add Category"}</button>
            {editId !== null && <button onClick={cancel} className="bg-slate-500">Cancel</button>}
          </div>
        </div>
        <div className="overflow-hidden rounded-xl bg-white shadow">
          {cats.length === 0 ? (
            <p className="p-8 text-center text-sm text-slate-400">No categories yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left">Name</th>
                  <th className="px-4 py-3 text-left">Type</th>
                  <th className="px-4 py-3 text-left">Created</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {cats.map((c, i) => (
                  <tr key={c.category_id} className={i % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                    <td className="px-4 py-3 font-medium">{c.name}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${TS[c.type]}`}>{c.type}</span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">{new Date(c.created_at).toLocaleDateString()}</td>
                    <td className="px-4 py-3 space-x-2 text-right">
                      <button onClick={() => startEdit(c)} className="bg-slate-700 px-3 py-1 text-xs">Edit</button>
                      <button onClick={() => del(c.category_id)} className="bg-red-600 px-3 py-1 text-xs">Delete</button>
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
