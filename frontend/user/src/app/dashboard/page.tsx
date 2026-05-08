"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import CategoryBreakdownChart from "@/components/CategoryBreakdownChart";
import MonthlyTrendChart from "@/components/MonthlyTrendChart";
import Navbar from "@/components/Navbar";
import SummaryChart from "@/components/SummaryChart";
import { useAuth } from "@/hooks/useAuth";
import api from "@/lib/api";

type MonthlyTrend = { month: string; income: number; expense: number };
type CategoryBreakdown = { category_name: string; total: number };
type Summary = {
  total_income: number;
  total_expense: number;
  balance: number;
  expense_ratio: number;
  savings_rate: number;
  monthly_average_income: number;
  monthly_average_expense: number;
  transaction_count: number;
  budget_total: number;
  budget_spent: number;
  budget_remaining: number;
  over_budget_count: number;
  budget_month: string;
  top_expense_category_name: string | null;
  top_expense_category_total: number;
  health_status: "healthy" | "watch" | "at_risk";
  focus_message: string;
  monthly_trend: MonthlyTrend[];
  category_breakdown: CategoryBreakdown[];
};

const HEALTH = {
  healthy: { card: "border-green-200 bg-green-50", text: "text-green-800", badge: "Healthy" },
  watch: { card: "border-amber-200 bg-amber-50", text: "text-amber-800", badge: "Watch" },
  at_risk: { card: "border-red-200 bg-red-50", text: "text-red-800", badge: "At Risk" },
};
const DEFAULT_MONTH = new Date().toISOString().slice(0, 7);

export default function DashboardPage() {
  const { user, loading } = useAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [selectedMonth, setSelectedMonth] = useState(DEFAULT_MONTH);

  useEffect(() => {
    if (!user) return;
    void api
      .get<Summary>("/dashboard/summary", { params: { month: `${selectedMonth}-01` } })
      .then((r) => setSummary(r.data));
  }, [user, selectedMonth]);

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center text-slate-400">Loading...</div>;
  }

  const fmt = (n: number) => n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
  const bal = summary?.balance ?? 0;
  const health = HEALTH[summary?.health_status ?? "healthy"];
  const budgetRemaining = summary?.budget_remaining ?? 0;

  return (
    <>
      <Navbar userName={user?.name} />
      <main className="mx-auto max-w-6xl space-y-8 p-6">
        <div>
          <h1 className="text-3xl font-bold text-ink">Dashboard</h1>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: "Total Income", val: `$${fmt(summary?.total_income ?? 0)}`, color: "text-green-600" },
            { label: "Total Expenses", val: `$${fmt(summary?.total_expense ?? 0)}`, color: "text-red-500" },
            { label: "Net Balance", val: `${bal < 0 ? "-" : ""}$${fmt(Math.abs(bal))}`, color: bal >= 0 ? "text-green-600" : "text-red-500" },
            { label: "Transactions", val: String(summary?.transaction_count ?? 0), color: "text-ink" },
          ].map((k) => (
            <div key={k.label} className="rounded-xl bg-white p-5 shadow">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{k.label}</p>
              <p className={`mt-1 text-2xl font-bold ${k.color}`}>{k.val}</p>
            </div>
          ))}
        </div>

        <div className={`rounded-xl border p-5 ${health.card}`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className={`text-xs font-semibold uppercase tracking-wide ${health.text}`}>Financial Health</p>
              <h2 className={`mt-1 text-xl font-bold ${health.text}`}>{health.badge}</h2>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg bg-white/80 p-3 shadow-sm">
                <p className="text-xs uppercase tracking-wide text-slate-400">Expense Ratio</p>
                <p className="mt-1 text-lg font-semibold text-ink">{pct(summary?.expense_ratio ?? 0)}</p>
              </div>
              <div className="rounded-lg bg-white/80 p-3 shadow-sm">
                <p className="text-xs uppercase tracking-wide text-slate-400">Savings Rate</p>
                <p className="mt-1 text-lg font-semibold text-ink">{pct(summary?.savings_rate ?? 0)}</p>
              </div>
              <div className="rounded-lg bg-white/80 p-3 shadow-sm">
                <p className="text-xs uppercase tracking-wide text-slate-400">Top Expense Category</p>
                <p className="mt-1 text-lg font-semibold text-ink">{summary?.top_expense_category_name ?? "None yet"}</p>
                {summary?.top_expense_category_name && <p className="text-xs text-slate-500">${fmt(summary?.top_expense_category_total ?? 0)}</p>}
              </div>
            </div>
          </div>
        </div>

        <div className="rounded-xl bg-white p-5 shadow">
          <h2 className="mb-2 font-semibold text-ink">Monthly Averages</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Average Income</p>
              <p className="mt-1 text-2xl font-bold text-green-600">${fmt(summary?.monthly_average_income ?? 0)}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Average Expense</p>
              <p className="mt-1 text-2xl font-bold text-red-500">${fmt(summary?.monthly_average_expense ?? 0)}</p>
            </div>
          </div>
        </div>

        <div className="rounded-xl bg-white p-5 shadow">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="mb-2 font-semibold text-ink">Budget Control</h2>
              <p className="text-sm text-slate-500">Budget month: {summary?.budget_month ?? selectedMonth}</p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label className="mb-1 block text-xs text-slate-500">Month</label>
                <input type="month" value={selectedMonth} onChange={(e) => setSelectedMonth(e.target.value)} className="text-sm" />
              </div>
              <Link href="/budgets" className="text-sm font-medium text-teal-700 hover:text-teal-800">
                Manage Budgets
              </Link>
            </div>
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Budgeted</p>
              <p className="mt-1 text-2xl font-bold text-ink">${fmt(summary?.budget_total ?? 0)}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Spent</p>
              <p className="mt-1 text-2xl font-bold text-red-500">${fmt(summary?.budget_spent ?? 0)}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">{budgetRemaining < 0 ? "Overspent" : "Remaining"}</p>
              <p className={`mt-1 text-2xl font-bold ${budgetRemaining >= 0 ? "text-green-600" : "text-red-500"}`}>
                ${fmt(Math.abs(budgetRemaining))}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Over Budget</p>
              <p className={`mt-1 text-2xl font-bold ${(summary?.over_budget_count ?? 0) > 0 ? "text-red-500" : "text-green-600"}`}>
                {summary?.over_budget_count ?? 0}
              </p>
            </div>
          </div>
          {!!summary?.budget_total && summary.over_budget_count > 0 && (
            <p className="mt-4 text-sm text-slate-600">
              {summary.over_budget_count} budget {summary.over_budget_count === 1 ? "category is" : "categories are"} over plan.
            </p>
          )}
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-xl bg-white p-5 shadow">
            <h2 className="mb-3 font-semibold text-ink">Income vs Expenses</h2>
            <SummaryChart income={summary?.total_income ?? 0} expense={summary?.total_expense ?? 0} />
          </div>
          <div className="rounded-xl bg-white p-5 shadow">
            <h2 className="mb-3 font-semibold text-ink">Expense Breakdown</h2>
            <CategoryBreakdownChart data={summary?.category_breakdown ?? []} />
          </div>
        </div>

        <div className="rounded-xl bg-white p-5 shadow">
          <h2 className="mb-3 font-semibold text-ink">Monthly Trend</h2>
          <MonthlyTrendChart data={summary?.monthly_trend ?? []} />
        </div>
      </main>
    </>
  );
}
