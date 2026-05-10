"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import axios from "axios";

import CategoryBreakdownChart from "@/components/CategoryBreakdownChart";
import MonthlyTrendChart from "@/components/MonthlyTrendChart";
import Navbar from "@/components/Navbar";
import SummaryChart from "@/components/SummaryChart";
import { useAuth } from "@/hooks/useAuth";
import api from "@/lib/api";
import {
  BUDGET_RECOMMENDATIONS_ROUTE,
  BudgetRecommendation,
  confidenceLabel as recommendationConfidenceLabel,
  confidenceTone as recommendationConfidenceTone,
  formatCurrency,
  formatPercent,
  formatSignedCurrency,
} from "@/lib/budgetRecommendations";

type MonthlyTrend = { month: string; income: number; expense: number };
type CategoryBreakdown = { category_name: string; total: number };
type SpendingForecast = {
  predicted_next_month_expense: number | null;
  confidence_level: "low" | "medium" | "high" | "unavailable";
  model_name: string;
  months_used: number;
  current_month_expense: number;
  previous_month_expense: number;
  rolling_3_month_expense_avg: number;
  budget_total: number;
  forecast_vs_budget: number | null;
  top_reduction_categories: string[];
  recommendation: string;
};
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
const FORECAST_UNAVAILABLE_MESSAGE = "Spending forecast is unavailable until more transaction history is available.";

export default function DashboardPage() {
  const { user, loading } = useAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [forecast, setForecast] = useState<SpendingForecast | null>(null);
  const [recommendations, setRecommendations] = useState<BudgetRecommendation[]>([]);
  const [recommendationsLoading, setRecommendationsLoading] = useState(false);
  const [recommendationsError, setRecommendationsError] = useState<string | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastError, setForecastError] = useState<string | null>(null);
  const [selectedMonth, setSelectedMonth] = useState(DEFAULT_MONTH);

  useEffect(() => {
    if (!user) return;
    void api
      .get<Summary>("/dashboard/summary", { params: { month: `${selectedMonth}-01` } })
      .then((r) => setSummary(r.data));
  }, [user, selectedMonth]);

  useEffect(() => {
    if (!user) return;
    setForecastLoading(true);
    setForecastError(null);
    void api
      .get<SpendingForecast>("/ml/forecast-spending")
      .then((r) => setForecast(r.data))
      .catch((error) => {
        setForecast(null);
        setForecastError(axios.isAxiosError(error) ? error.message : "Unable to load spending forecast.");
      })
      .finally(() => setForecastLoading(false));
  }, [user]);

  useEffect(() => {
    if (!user) return;
    setRecommendationsLoading(true);
    setRecommendationsError(null);
    void api
      .get<BudgetRecommendation[]>(BUDGET_RECOMMENDATIONS_ROUTE)
      .then((r) => setRecommendations(r.data))
      .catch((error) => {
        setRecommendations([]);
        setRecommendationsError(axios.isAxiosError(error) ? error.message : "Unable to load budget recommendations.");
      })
      .finally(() => setRecommendationsLoading(false));
  }, [user]);

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center text-slate-400">Loading...</div>;
  }

  const fmt = (n: number) => n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
  const bal = summary?.balance ?? 0;
  const health = HEALTH[summary?.health_status ?? "healthy"];
  const budgetRemaining = summary?.budget_remaining ?? 0;
  const forecastUnavailable =
    !forecast || forecast.confidence_level === "unavailable" || forecast.predicted_next_month_expense === null;
  const forecastOverBudget = !forecastUnavailable && (forecast.forecast_vs_budget ?? 0) > 0;
  const forecastBudgetDelta = forecast?.forecast_vs_budget ?? null;
  const forecastMessage = forecastUnavailable
    ? FORECAST_UNAVAILABLE_MESSAGE
    : forecastOverBudget
      ? `Your forecasted spending for next month may exceed your budget. Consider reducing ${
          forecast.top_reduction_categories[0] ?? "your highest-spending"
        } and ${forecast.top_reduction_categories[1] ?? "other high-spending"} expenses.`
      : "Your forecasted spending appears to be within your current budget. Continue monitoring your highest spending categories.";
  const forecastTone = forecastUnavailable
    ? "border-slate-200 bg-slate-50 text-slate-700"
    : forecastOverBudget
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : "border-green-200 bg-green-50 text-green-900";
  const confidenceTone =
    forecast?.confidence_level === "high"
      ? "bg-green-100 text-green-800"
      : forecast?.confidence_level === "medium"
        ? "bg-blue-100 text-blue-800"
        : forecast?.confidence_level === "low"
          ? "bg-amber-100 text-amber-800"
          : "bg-slate-200 text-slate-700";
  const confidenceLabel = forecastLoading
    ? "Loading"
    : `${forecast?.confidence_level?.charAt(0).toUpperCase() ?? "U"}${forecast?.confidence_level?.slice(1) ?? "navailable"}`;
  const topRecommendations = [...recommendations]
    .sort((left, right) => Math.abs(right.expected_change_amount) - Math.abs(left.expected_change_amount))
    .slice(0, 3);

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

        <div className="rounded-xl bg-white p-5 shadow">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold text-ink">Predicted Next-Month Spending</h2>
            </div>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${confidenceTone}`}>
              Confidence: {confidenceLabel}
            </span>
          </div>

          {forecastLoading ? (
            <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
              Loading spending forecast...
            </div>
          ) : (
            <>
              <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
                <div>
                  <p className="text-xs uppercase tracking-wide text-slate-400">Predicted Spend</p>
                  <p className="mt-1 text-2xl font-bold text-ink">
                    {forecastUnavailable ? "Unavailable" : `$${fmt(forecast?.predicted_next_month_expense ?? 0)}`}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-slate-400">Current Month</p>
                  <p className="mt-1 text-xl font-semibold text-ink">${fmt(forecast?.current_month_expense ?? 0)}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-slate-400">Budget Total</p>
                  <p className="mt-1 text-xl font-semibold text-ink">${fmt(forecast?.budget_total ?? 0)}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-slate-400">Forecast vs Budget</p>
                  <p
                    className={`mt-1 text-xl font-semibold ${
                      (forecastBudgetDelta ?? 0) > 0 ? "text-amber-700" : "text-green-700"
                    }`}
                  >
                    {forecastBudgetDelta === null
                      ? "Unavailable"
                      : `${forecastBudgetDelta >= 0 ? "+" : "-"}$${fmt(Math.abs(forecastBudgetDelta))}`}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-slate-400">3-Month Average</p>
                  <p className="mt-1 text-xl font-semibold text-ink">${fmt(forecast?.rolling_3_month_expense_avg ?? 0)}</p>
                </div>
              </div>

              <div className={`mt-4 rounded-lg border p-4 ${forecastTone}`}>
                <p className="text-sm font-medium">{forecastMessage}</p>
                {!!forecast?.top_reduction_categories.length && !forecastUnavailable && (
                  <p className="mt-2 text-xs text-current/80">
                    Highest spending categories: {forecast.top_reduction_categories.join(", ")}
                  </p>
                )}
                {forecastError && <p className="mt-2 text-xs text-current/80">Forecast service note: {forecastError}</p>}
              </div>
            </>
          )}
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-xl bg-white p-5 shadow">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold text-ink">Recommended Budget Adjustments</h2>
                <p className="mt-1 text-sm text-slate-500">Top categories that may need budget changes.</p>
              </div>
              <Link href="/budgets" className="text-sm font-medium text-teal-700 hover:text-teal-800">
                View all
              </Link>
            </div>

            {recommendationsLoading ? (
              <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
                Loading recommendations...
              </div>
            ) : recommendationsError ? (
              <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
                Budget recommendations are unavailable right now.
              </div>
            ) : topRecommendations.length === 0 ? (
              <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
                No budget recommendations available yet.
              </div>
            ) : (
              <div className="mt-4 space-y-4">
                {topRecommendations.map((recommendation) => {
                  const isIncrease = recommendation.expected_change_amount >= 0;
                  const changeTone = isIncrease
                    ? "border-amber-100 bg-amber-50 text-amber-700"
                    : "border-emerald-100 bg-emerald-50 text-emerald-700";

                  return (
                    <div
                      key={recommendation.category_id}
                      className="rounded-2xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-white p-4 shadow-sm ring-1 ring-slate-100"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <h3 className="font-semibold text-ink">{recommendation.category_name}</h3>
                          <p className="mt-2 text-xs text-slate-500">
                            Current: <span className="font-semibold text-slate-700">${formatCurrency(recommendation.current_budget)}</span>
                          </p>
                        </div>
                        <span
                          className={`rounded-full px-3 py-1 text-xs font-semibold ${recommendationConfidenceTone(recommendation.confidence_level)}`}
                        >
                          {recommendationConfidenceLabel(recommendation.confidence_level)} confidence
                        </span>
                      </div>

                      <div className="mt-4">
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Recommended</p>
                        <p className="mt-1 text-2xl font-bold tracking-tight text-ink">
                          ${formatCurrency(recommendation.recommended_budget)}
                        </p>
                      </div>

                      <div className="mt-4 grid gap-3 sm:grid-cols-2">
                        <div className={`rounded-xl border px-3 py-2 ${changeTone}`}>
                          <p className="text-xs font-semibold uppercase tracking-wide opacity-75">Difference</p>
                          <p className="mt-1 text-sm font-bold">{formatSignedCurrency(recommendation.expected_change_amount)}</p>
                        </div>
                        <div className={`rounded-xl border px-3 py-2 ${changeTone}`}>
                          <p className="text-xs font-semibold uppercase tracking-wide opacity-75">Change</p>
                          <p className="mt-1 text-sm font-bold">{formatPercent(recommendation.expected_change_percent)}</p>
                        </div>
                      </div>

                      <div className="mt-4 rounded-xl border border-blue-100 border-l-4 border-l-blue-500 bg-blue-50/80 px-3 py-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Recommendation</p>
                        <p className="mt-1 text-sm leading-6 text-slate-700">{recommendation.reason}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {recommendationsError && <p className="mt-3 text-xs text-slate-400">Service note: {recommendationsError}</p>}
          </div>

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
