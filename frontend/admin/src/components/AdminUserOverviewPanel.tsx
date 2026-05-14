"use client";

import BizMoneyLoader from "@/components/BizMoneyLoader";
import { formatCompactNumber, formatCurrency, formatDate, formatDateTime } from "@/lib/format";
import { AdminUserOverview } from "@/lib/types";

type AdminUserOverviewPanelProps = {
  overview: AdminUserOverview | null;
  loading?: boolean;
  error?: string;
};

export default function AdminUserOverviewPanel({
  overview,
  loading = false,
  error = "",
}: AdminUserOverviewPanelProps) {
  if (loading && !overview) {
    return <BizMoneyLoader minHeightClassName="min-h-64" label="Loading selected user" />;
  }

  if (error) {
    return <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{error}</div>;
  }

  if (!overview) {
    return null;
  }

  const user = overview.user;
  const financial = overview.financial_summary;

  return (
    <div className={`space-y-5 transition-opacity ${loading ? "opacity-70" : "opacity-100"}`}>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,440px)]">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">Selected Account</p>
              <h3 className="mt-2 text-2xl font-semibold text-slate-950">{user.name}</h3>
              <p className="text-sm text-slate-500">{user.email}</p>
            </div>
            <span
              className={`w-fit rounded-full px-3 py-1 text-xs font-semibold ${
                user.is_active ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"
              }`}
            >
              {user.is_active ? "Active" : "Inactive"}
            </span>
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Created</p>
              <p className="mt-1 text-sm font-medium text-slate-800">{formatDate(user.created_at)}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Last activity</p>
              <p className="mt-1 text-sm font-medium text-slate-800">{formatDateTime(user.last_activity)}</p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Metric label="Income" value={formatCurrency(financial.total_income)} tone="text-emerald-700" />
          <Metric label="Expense" value={formatCurrency(financial.total_expense)} tone="text-rose-700" />
          <Metric label="Balance" value={formatCurrency(financial.balance)} tone={financial.balance >= 0 ? "text-slate-900" : "text-rose-700"} />
          <Metric label="Over Budget" value={formatCompactNumber(financial.over_budget_count)} tone="text-amber-700" />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-4">
        <Metric label="Transactions" value={formatCompactNumber(user.transactions_count)} />
        <Metric label="Categories" value={formatCompactNumber(user.categories_count)} />
        <Metric label="Budgets" value={formatCompactNumber(user.budgets_count)} />
        <Metric label="Insights" value={formatCompactNumber(user.insights_count)} />
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <section>
          <h4 className="text-sm font-semibold text-slate-900">Recent Activity</h4>
          {overview.recent_logs.length > 0 ? (
            <div className="mt-3 space-y-3">
              {overview.recent_logs.map((log) => (
                <div key={log.log_id} className="border-l-2 border-slate-300 pl-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-slate-900">{log.event_type}</span>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{log.level}</span>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">{log.message}</p>
                  <p className="mt-1 text-xs text-slate-400">{formatDateTime(log.created_at)}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-400">No recent activity has been recorded for this user.</p>
          )}
        </section>

        <section>
          <h4 className="text-sm font-semibold text-slate-900">Recent Insights</h4>
          {overview.recent_insights.length > 0 ? (
            <div className="mt-3 space-y-3">
              {overview.recent_insights.map((insight) => (
                <div key={insight.insight_id} className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-900">{insight.title}</p>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                        insight.severity === "critical"
                          ? "bg-rose-100 text-rose-700"
                          : insight.severity === "warning"
                            ? "bg-amber-100 text-amber-700"
                            : "bg-sky-100 text-sky-700"
                      }`}
                    >
                      {insight.severity}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">{insight.message}</p>
                  <p className="mt-2 text-xs text-slate-400">{formatDateTime(insight.created_at)}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-400">No recent insights are available for this user.</p>
          )}
        </section>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone = "text-slate-900",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-xs uppercase tracking-[0.18em] text-slate-400">{label}</p>
      <p className={`mt-2 text-xl font-semibold ${tone}`}>{value}</p>
    </div>
  );
}
