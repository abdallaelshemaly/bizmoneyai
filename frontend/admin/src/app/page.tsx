"use client";

import axios from "axios";
import { useCallback, useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import AdminMetricCard from "@/components/AdminMetricCard";
import AdminPanel from "@/components/AdminPanel";
import AdminShell from "@/components/AdminShell";
import AdminUserOverviewPanel from "@/components/AdminUserOverviewPanel";
import AdminUserSelector from "@/components/AdminUserSelector";
import api from "@/lib/api";
import { getErrorMessage, getStatusCode } from "@/lib/errors";
import { formatCompactNumber, formatCurrency, formatDate, formatDateTime } from "@/lib/format";
import {
  AdminAnalyticsBudgets,
  AdminAnalyticsInsights,
  AdminAnalyticsOverview,
  AdminAnalyticsTransactions,
  AdminAnalyticsUsers,
  AdminDashboard,
  AdminUserOverview,
  AdminUsersResponse,
} from "@/lib/types";

const PIE_COLORS = ["#0f172a", "#14b8a6", "#38bdf8", "#f97316", "#ef4444", "#8b5cf6"];

export default function AdminDashboardPage() {
  const [data, setData] = useState<AdminDashboard | null>(null);
  const [users, setUsers] = useState<AdminUsersResponse["users"]>([]);
  const [userOverview, setUserOverview] = useState<AdminUserOverview | null>(null);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [usersError, setUsersError] = useState("");
  const [overviewError, setOverviewError] = useState("");
  const [loading, setLoading] = useState(true);
  const [usersLoading, setUsersLoading] = useState(true);
  const [overviewLoading, setOverviewLoading] = useState(false);

  const selectedUser = userOverview?.user ?? users.find((user) => user.user_id === selectedUserId) ?? null;
  const isInitialLoading = loading && !data;
  const isRefreshing = loading && !!data;

  const loadUsers = useCallback(async (signal?: AbortSignal) => {
    setUsersLoading(true);
    try {
      const response = await api.get<AdminUsersResponse>("/admin/users", {
        params: { limit: 500, offset: 0, sort_by: "name", sort_order: "asc" },
        signal,
      });
      setUsers(response.data.users);
      setUsersError("");
      if (selectedUserId !== null && !response.data.users.some((user) => user.user_id === selectedUserId)) {
        setSelectedUserId(null);
        setUserOverview(null);
        setOverviewError("The selected user is no longer available. Returned to global mode.");
      }
    } catch (err: unknown) {
      if (axios.isCancel(err)) {
        return;
      }
      if (getStatusCode(err) !== 401 && getStatusCode(err) !== 403) {
        setUsersError(getErrorMessage(err, "Failed to load users for analytics scoping."));
      }
    } finally {
      if (!signal?.aborted) {
        setUsersLoading(false);
      }
    }
  }, [selectedUserId]);

  const loadDashboard = useCallback(async (userId: number | null, signal?: AbortSignal) => {
    setLoading(true);
    try {
      const params = {
        user_id: userId ?? undefined,
      };
      const [overview, transactions, usersAnalytics, insights, budgets] = await Promise.all([
        api.get<AdminAnalyticsOverview>("/admin/analytics/overview", { params, signal }),
        api.get<AdminAnalyticsTransactions>("/admin/analytics/transactions", { params, signal }),
        api.get<AdminAnalyticsUsers>("/admin/analytics/users", { params, signal }),
        api.get<AdminAnalyticsInsights>("/admin/analytics/insights", { params, signal }),
        api.get<AdminAnalyticsBudgets>("/admin/analytics/budgets", { params, signal }),
      ]);
      setData({
        ...overview.data,
        ...transactions.data,
        ...usersAnalytics.data,
        ...insights.data,
        ...budgets.data,
      });
      setError("");
    } catch (err: unknown) {
      if (axios.isCancel(err)) {
        return;
      }
      if (getStatusCode(err) !== 401 && getStatusCode(err) !== 403) {
        if (getStatusCode(err) === 404 && userId !== null) {
          setSelectedUserId(null);
          setUserOverview(null);
          setOverviewError("The selected user could not be found. Returned to global mode.");
        }
        setError(getErrorMessage(err, "Failed to load the admin dashboard."));
      }
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, []);

  const loadUserOverview = useCallback(async (userId: number | null, signal?: AbortSignal) => {
    if (userId === null) {
      setUserOverview(null);
      setOverviewError("");
      setOverviewLoading(false);
      return;
    }

    setOverviewLoading(true);
    try {
      const response = await api.get<AdminUserOverview>(`/admin/users/${userId}/overview`, { signal });
      setUserOverview(response.data);
      setOverviewError("");
    } catch (err: unknown) {
      if (axios.isCancel(err)) {
        return;
      }
      if (getStatusCode(err) === 404) {
        setSelectedUserId(null);
        setUserOverview(null);
        setOverviewError("The selected user was deleted or is no longer available. Returned to global mode.");
      } else if (getStatusCode(err) !== 401 && getStatusCode(err) !== 403) {
        setOverviewError(getErrorMessage(err, "Failed to load the selected user overview."));
      }
    } finally {
      if (!signal?.aborted) {
        setOverviewLoading(false);
      }
    }
  }, []);

  const refreshDashboard = useCallback(async () => {
    await Promise.all([loadUsers(), loadDashboard(selectedUserId), loadUserOverview(selectedUserId)]);
  }, [loadDashboard, loadUserOverview, loadUsers, selectedUserId]);

  const handleScopeChange = useCallback((userId: number | null) => {
    setSelectedUserId(userId);
    setError("");
    setOverviewError("");
    setUserOverview(null);
    setLoading(true);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadUsers(controller.signal);
    return () => controller.abort();
  }, [loadUsers]);

  useEffect(() => {
    const controller = new AbortController();
    void loadDashboard(selectedUserId, controller.signal);
    return () => controller.abort();
  }, [loadDashboard, selectedUserId]);

  useEffect(() => {
    const controller = new AbortController();
    void loadUserOverview(selectedUserId, controller.signal);
    return () => controller.abort();
  }, [loadUserOverview, selectedUserId]);

  const totalTransactionVolume = data?.transaction_trends.reduce((sum, item) => sum + item.total_amount, 0) ?? 0;
  return (
    <AdminShell
      title="Monitoring Dashboard"
      actions={
        <button onClick={() => void refreshDashboard()} className="bg-white px-4 py-2 text-sm text-slate-700 shadow-sm ring-1 ring-slate-200">
          Refresh
        </button>
      }
    >
      <div className="space-y-6">
        {error && <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        <AdminPanel title="User Management Context">
          <div className="space-y-5">
            <AdminUserSelector
              users={users}
              value={selectedUserId}
              onChange={handleScopeChange}
              disabled={usersLoading && users.length === 0}
              loading={loading || usersLoading || overviewLoading}
            />

            {isRefreshing && <p className="text-sm font-medium text-teal-700">Updating analytics...</p>}
            {usersError && <p className="text-sm text-amber-700">{usersError}</p>}
            {selectedUserId === null && overviewError && <p className="text-sm text-amber-700">{overviewError}</p>}

            {selectedUserId !== null && (
              <AdminUserOverviewPanel
                overview={userOverview}
                loading={overviewLoading}
                error={overviewError}
              />
            )}
          </div>
        </AdminPanel>

        {isInitialLoading || !data ? (
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="h-56 animate-pulse rounded-2xl bg-white shadow-sm" />
            <div className="h-56 animate-pulse rounded-2xl bg-white shadow-sm" />
            <div className="h-56 animate-pulse rounded-2xl bg-white shadow-sm" />
            <div className="h-56 animate-pulse rounded-2xl bg-white shadow-sm" />
          </div>
        ) : (
          <div className={`space-y-6 transition-opacity ${isRefreshing ? "opacity-80" : "opacity-100"}`}>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-9">
              <AdminMetricCard
                label={selectedUser ? "Scoped User" : "Total Users"}
                value={formatCompactNumber(data.total_users)}
                helper={selectedUser ? selectedUser.email : "Registered user accounts"}
              />
              <AdminMetricCard label="Transactions" value={formatCompactNumber(data.total_transactions)} helper={formatCurrency(totalTransactionVolume)} tone="success" />
              <AdminMetricCard
                label="Categories"
                value={formatCompactNumber(data.total_categories)}
                helper={selectedUser ? "Categories for the selected user" : "Across all users"}
              />
              <AdminMetricCard
                label="Budgets"
                value={formatCompactNumber(data.total_budgets)}
                helper={selectedUser ? "Budget rules for the selected user" : "Active monitoring rules"}
              />
              <AdminMetricCard
                label="AI Insights"
                value={formatCompactNumber(data.total_ai_insights)}
                helper={selectedUser ? "Persisted insights for the selected user" : "Persisted generated insights"}
              />
              <AdminMetricCard
                label="Unusual Tx"
                value={formatCompactNumber(data.total_unusual_transactions)}
                tone={data.unusual_critical_count > 0 ? "danger" : data.unusual_warning_count > 0 ? "warning" : "default"}
              />
              <AdminMetricCard
                label="Forecast Risk Insights"
                value={formatCompactNumber(data.forecast_risk_insights_count)}
                helper={`${formatCompactNumber(data.users_with_forecast_risk)} users impacted`}
                tone={
                  data.forecast_risk_critical_count > 0
                    ? "danger"
                    : data.forecast_risk_warning_count > 0
                      ? "warning"
                      : "default"
                }
              />
              <AdminMetricCard
                label="Over Budget"
                value={formatCompactNumber(data.over_budget_categories)}
                helper={selectedUser ? "Budget rows above limit for this user" : "Budget rows above limit"}
                tone="warning"
              />
              <AdminMetricCard
                label="Overspending"
                value={formatCurrency(data.total_overspending_amount)}
                tone="danger"
              />
            </div>

            <AdminPanel
              title="Unusual Transaction Monitoring"
              description={
                selectedUser
                  ? "Recent Model 2 warnings created for the selected user's transactions."
                  : "Recent Model 2 warnings created from transaction creation events."
              }
            >
              <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                  <div className="rounded-xl bg-amber-50 px-4 py-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-700">Warnings</p>
                    <p className="mt-1 text-2xl font-semibold text-amber-800">{formatCompactNumber(data.unusual_warning_count)}</p>
                  </div>
                  <div className="rounded-xl bg-rose-50 px-4 py-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-rose-700">Critical</p>
                    <p className="mt-1 text-2xl font-semibold text-rose-800">{formatCompactNumber(data.unusual_critical_count)}</p>
                  </div>
                </div>
                {data.recent_unusual_transaction_insights.length > 0 ? (
                  <div className="space-y-3">
                    {data.recent_unusual_transaction_insights.map((insight) => (
                      <div key={insight.insight_id} className="rounded-xl bg-slate-50 px-4 py-3">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <p className="font-medium text-slate-900">{insight.title}</p>
                            <p className="text-sm text-slate-500">{insight.message}</p>
                            <p className="mt-1 text-xs text-slate-400">
                              {insight.user_name} | {formatDateTime(insight.created_at)}
                            </p>
                          </div>
                          <div className="text-right">
                            <span
                              className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                                insight.severity === "critical"
                                  ? "bg-rose-100 text-rose-700"
                                  : "bg-amber-100 text-amber-700"
                              }`}
                            >
                              {insight.severity}
                            </span>
                            {insight.fraud_probability !== null && (
                              <p className="mt-2 text-xs text-slate-500">
                                {(insight.fraud_probability * 100).toFixed(1)}% probability
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">
                    {selectedUser ? "No unusual transaction insights for this user yet." : "No unusual transaction insights have been recorded yet."}
                  </p>
                )}
              </div>
            </AdminPanel>

            <AdminPanel
              title="Forecast Risk Monitoring"
              description={
                selectedUser
                  ? "Recent forecast-based budget risk insights recorded for the selected user."
                  : "Recent persisted spending forecast risk insights across users."
              }
            >
              <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
                <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
                  <div className="rounded-xl bg-amber-50 px-4 py-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-700">Warnings</p>
                    <p className="mt-1 text-2xl font-semibold text-amber-800">{formatCompactNumber(data.forecast_risk_warning_count)}</p>
                  </div>
                  <div className="rounded-xl bg-rose-50 px-4 py-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-rose-700">Critical</p>
                    <p className="mt-1 text-2xl font-semibold text-rose-800">{formatCompactNumber(data.forecast_risk_critical_count)}</p>
                  </div>
                  <div className="rounded-xl bg-sky-50 px-4 py-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">Users</p>
                    <p className="mt-1 text-2xl font-semibold text-sky-800">{formatCompactNumber(data.users_with_forecast_risk)}</p>
                  </div>
                </div>
                {data.recent_forecast_risk_insights.length > 0 ? (
                  <div className="space-y-3">
                    {data.recent_forecast_risk_insights.map((insight) => (
                      <div key={insight.insight_id} className="rounded-xl bg-slate-50 px-4 py-3">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <p className="font-medium text-slate-900">{insight.title}</p>
                            <p className="text-sm text-slate-500">{insight.message}</p>
                            <p className="mt-1 text-xs text-slate-400">
                              {insight.user_name} | {formatDateTime(insight.created_at)}
                            </p>
                            {insight.top_reduction_categories.length > 0 && (
                              <p className="mt-2 text-xs text-slate-500">
                                Focus categories: {insight.top_reduction_categories.join(", ")}
                              </p>
                            )}
                          </div>
                          <div className="text-right">
                            <span
                              className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                                insight.severity === "critical"
                                  ? "bg-rose-100 text-rose-700"
                                  : "bg-amber-100 text-amber-700"
                              }`}
                            >
                              {insight.severity}
                            </span>
                            {insight.forecast_vs_budget !== null && (
                              <p className="mt-2 text-xs text-slate-500">
                                {formatCurrency(insight.forecast_vs_budget)} over budget
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">
                    {selectedUser ? "No forecast risk insights for this user yet." : "No forecast risk insights have been recorded yet."}
                  </p>
                )}
              </div>
            </AdminPanel>

            <div className="grid gap-6 xl:grid-cols-2">
              <AdminPanel
                title="Transactions Over Time"
                description={
                  selectedUser
                    ? "Daily transaction volume and total movement across the selected monitoring window for this user."
                    : "Daily transaction volume and total movement across the selected monitoring window."
                }
              >
                {data.transaction_trends.some((item) => item.transactions_count > 0 || item.total_amount > 0) ? (
                  <div className="h-80">
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={data.transaction_trends}>
                        <defs>
                          <linearGradient id="transactionArea" x1="0" x2="0" y1="0" y2="1">
                            <stop offset="5%" stopColor="#14b8a6" stopOpacity={0.42} />
                            <stop offset="95%" stopColor="#14b8a6" stopOpacity={0.05} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(value) => formatDate(value)} />
                        <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
                        <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} tickFormatter={(value) => `$${value}`} />
                        <Tooltip
                          formatter={(value: number, name: string) =>
                            name === "total_amount" ? formatCurrency(value) : value.toLocaleString("en-US")
                          }
                          labelFormatter={(value) => formatDate(String(value))}
                        />
                        <Legend />
                        <Area yAxisId="right" type="monotone" dataKey="total_amount" name="Amount" stroke="#14b8a6" fill="url(#transactionArea)" strokeWidth={2} />
                        <Bar yAxisId="left" dataKey="transactions_count" name="Transactions" fill="#0f172a" radius={[6, 6, 0, 0]} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">{selectedUser ? "No transaction activity for this user yet." : "No transaction activity yet."}</p>
                )}
              </AdminPanel>

              <AdminPanel
                title={selectedUser ? "User Activity Over Time" : "Platform Activity Over Time"}
                description={
                  selectedUser
                    ? "Combined transaction, category, budget, insight, and log activity by day for the selected user."
                    : "Combined user, transaction, category, budget, insight, and log activity by day."
                }
              >
                {data.activity_trends.some((item) => item.total_events > 0) ? (
                  <div className="h-80">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={data.activity_trends}>
                        <defs>
                          <linearGradient id="eventArea" x1="0" x2="0" y1="0" y2="1">
                            <stop offset="5%" stopColor="#0f172a" stopOpacity={0.28} />
                            <stop offset="95%" stopColor="#0f172a" stopOpacity={0.05} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(value) => formatDate(value)} />
                        <YAxis tick={{ fontSize: 11 }} />
                        <Tooltip labelFormatter={(value) => formatDate(String(value))} />
                        <Legend />
                        <Area type="monotone" dataKey="total_events" name="Total events" stroke="#0f172a" fill="url(#eventArea)" strokeWidth={2} />
                        <Area type="monotone" dataKey="transactions" name="Transactions" stroke="#14b8a6" fillOpacity={0} strokeWidth={2} />
                        <Area type="monotone" dataKey="logs" name="Logs" stroke="#f97316" fillOpacity={0} strokeWidth={2} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">{selectedUser ? "No scoped activity has been recorded yet." : "No platform events recorded yet."}</p>
                )}
              </AdminPanel>

              <AdminPanel
                title="Insight Severity Distribution"
                description={
                  selectedUser
                    ? "Breakdown of generated AI insight severity levels for the selected user."
                    : "Breakdown of generated AI insight severity levels."
                }
              >
                {data.insight_severity_distribution.length > 0 ? (
                  <div className="grid gap-6 lg:grid-cols-[1fr_220px]">
                    <div className="h-72">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={data.insight_severity_distribution}
                            dataKey="count"
                            nameKey="label"
                            outerRadius={90}
                            innerRadius={52}
                            paddingAngle={4}
                          >
                            {data.insight_severity_distribution.map((entry, index) => (
                              <Cell key={entry.label} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                            ))}
                          </Pie>
                          <Tooltip formatter={(value: number) => value.toLocaleString("en-US")} />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="space-y-3">
                      {data.insight_severity_distribution.map((item, index) => (
                        <div key={item.label} className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3">
                          <div className="flex items-center gap-3">
                            <span
                              className="h-3 w-3 rounded-full"
                              style={{ backgroundColor: PIE_COLORS[index % PIE_COLORS.length] }}
                            />
                            <span className="text-sm font-medium capitalize text-slate-700">{item.label}</span>
                          </div>
                          <span className="text-sm text-slate-500">{item.count}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">{selectedUser ? "No AI insights have been generated for this user yet." : "No AI insights have been generated yet."}</p>
                )}
              </AdminPanel>

              <AdminPanel
                title="Expense Distribution"
                description={
                  selectedUser
                    ? "Top recent expense categories for the selected user by total value and transaction count."
                    : "Top recent expense categories by total value and transaction count."
                }
              >
                {data.spend_distribution.length > 0 ? (
                  <div className="h-80">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={data.spend_distribution} layout="vertical" margin={{ left: 24 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(value) => `$${value}`} />
                        <YAxis type="category" dataKey="category_name" width={110} tick={{ fontSize: 11 }} />
                        <Tooltip formatter={(value: number) => formatCurrency(value)} />
                        <Bar dataKey="total_amount" name="Expense total" fill="#0f172a" radius={[0, 8, 8, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">{selectedUser ? "No expense distribution data is available for this user yet." : "No expense distribution data is available yet."}</p>
                )}
              </AdminPanel>
            </div>

            <div className="grid gap-6 xl:grid-cols-2">
              <AdminPanel
                title="Top Overspending Categories"
                description={
                  selectedUser
                    ? "Budget categories where the selected user exceeded limits the most."
                    : "Budget categories with the highest overspending amount."
                }
              >
                {data.top_overspending_categories.length > 0 ? (
                  <div className="space-y-3">
                    {data.top_overspending_categories.map((item) => (
                      <div key={item.category_name} className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3">
                        <div>
                          <p className="font-medium text-slate-900">{item.category_name}</p>
                          <p className="text-sm text-slate-500">{item.over_budget_count} over-budget budgets</p>
                        </div>
                        <p className="text-sm font-semibold text-rose-600">{formatCurrency(item.total_overspent)}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">{selectedUser ? "This user has no overspending categories at the moment." : "No overspending categories at the moment."}</p>
                )}
              </AdminPanel>

              <AdminPanel
                title={selectedUser ? "Selected User Activity" : "Most Active Users"}
                description={
                  selectedUser
                    ? "Activity footprint across transactions, categories, budgets, and insights for the selected user."
                    : "Users with the highest combined transactions, categories, budgets, and insight activity."
                }
              >
                {data.most_active_users.length > 0 ? (
                  <div className="space-y-3">
                    {data.most_active_users.map((item) => (
                      <div key={item.user_id} className="rounded-2xl bg-slate-50 px-4 py-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="font-medium text-slate-900">{item.name}</p>
                            <p className="text-sm text-slate-500">{item.email}</p>
                          </div>
                          <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-semibold text-white">
                            Score {item.activity_score}
                          </span>
                        </div>
                        <div className="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-4">
                          <span>{item.transactions_count} transactions</span>
                          <span>{item.categories_count} categories</span>
                          <span>{item.budgets_count} budgets</span>
                          <span>{item.insights_count} insights</span>
                        </div>
                        <p className="mt-2 text-xs text-slate-400">Last activity: {formatDateTime(item.last_activity)}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">{selectedUser ? "No activity has been recorded for this user yet." : "No user activity has been recorded yet."}</p>
                )}
              </AdminPanel>
            </div>

            <AdminPanel
              title={selectedUser ? "Recent User Logs" : "Recent System Logs"}
              description={
                selectedUser
                  ? "Latest operational events recorded for the selected user."
                  : "Latest operational events recorded in the system log table."
              }
            >
              {data.recent_logs.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead className="bg-slate-50 text-left text-xs uppercase tracking-[0.2em] text-slate-500">
                      <tr>
                        <th className="px-4 py-3">Time</th>
                        <th className="px-4 py-3">Event</th>
                        <th className="px-4 py-3">Level</th>
                        <th className="px-4 py-3">Actor</th>
                        <th className="px-4 py-3">Message</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.recent_logs.map((log, index) => (
                        <tr key={log.log_id} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/70"}>
                          <td className="px-4 py-3 text-slate-500">{formatDateTime(log.created_at)}</td>
                          <td className="px-4 py-3 font-medium text-slate-900">{log.event_type}</td>
                          <td className="px-4 py-3">
                            <span
                              className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                                log.level === "warning"
                                  ? "bg-amber-100 text-amber-700"
                                  : log.level === "error" || log.level === "critical"
                                    ? "bg-rose-100 text-rose-700"
                                    : "bg-emerald-100 text-emerald-700"
                              }`}
                            >
                              {log.level}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-slate-600">
                            {log.admin_name || log.user_name || "System"}
                            <div className="text-xs text-slate-400">{log.admin_email || log.user_email || "background task"}</div>
                          </td>
                          <td className="max-w-[420px] px-4 py-3 text-slate-500">{log.message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-sm text-slate-400">{selectedUser ? "No logs are associated with this user yet." : "No system logs recorded yet."}</p>
              )}
            </AdminPanel>
          </div>
        )}
      </div>
    </AdminShell>
  );
}
