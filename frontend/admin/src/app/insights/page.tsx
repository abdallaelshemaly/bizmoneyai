"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import BizMoneyLoader from "@/components/BizMoneyLoader";
import AdminMetricCard from "@/components/AdminMetricCard";
import AdminPanel from "@/components/AdminPanel";
import AdminShell from "@/components/AdminShell";
import DataTable, { DataTableColumn, DataTableFilterConfig } from "@/components/DataTable";
import { useAdminDataTable } from "@/hooks/useAdminDataTable";
import api from "@/lib/api";
import { formatCompactNumber, formatDate, formatDateTime } from "@/lib/format";
import { AdminInsightRow, AdminInsightsResponse, AdminUsersResponse } from "@/lib/types";

const PIE_COLORS = ["#0f172a", "#14b8a6", "#f97316", "#ef4444", "#8b5cf6"];

export default function AdminInsightsPage() {
  const usersQuery = useQuery({
    queryKey: ["admin-insight-user-options"],
    queryFn: async () => {
      const response = await api.get<AdminUsersResponse>("/admin/users", {
        params: { limit: 500, offset: 0, sort_by: "name", sort_order: "asc" },
      });
      return response.data.users;
    },
  });

  const table = useAdminDataTable<AdminInsightsResponse, AdminInsightRow>({
    queryKey: "admin-insights",
    endpoint: "/admin/insights",
    extractRows: (response) => response.insights,
    extractTotal: (response) => response.total,
    initialFilters: {
      user_id: "",
      severity: "",
      priority: "",
      date_from: "",
      date_to: "",
    },
    initialLimit: 10,
    defaultSort: { key: "priority_score", order: "desc" },
    errorMessage: "Failed to load AI insights.",
  });

  const filters: DataTableFilterConfig[] = [
    {
      key: "user_id",
      type: "select",
      options: [
        { label: "All users", value: "" },
        ...(usersQuery.data ?? []).map((user) => ({
          label: user.name,
          value: String(user.user_id),
        })),
      ],
    },
    {
      key: "severity",
      type: "select",
      options: [
        { label: "All severities", value: "" },
        { label: "Info", value: "info" },
        { label: "Warning", value: "warning" },
        { label: "Critical", value: "critical" },
      ],
    },
    {
      key: "priority",
      type: "select",
      options: [
        { label: "All priorities", value: "" },
        { label: "Critical priority", value: "critical" },
        { label: "High priority", value: "high" },
        { label: "Medium priority", value: "medium" },
        { label: "Low priority", value: "low" },
      ],
    },
    { key: "date_from", type: "date" },
    { key: "date_to", type: "date" },
  ];

  const priorityBadgeClassName = (priorityLevel: AdminInsightRow["priority_level"]) => {
    if (priorityLevel === "critical") {
      return "bg-rose-100 text-rose-700";
    }
    if (priorityLevel === "high") {
      return "bg-orange-100 text-orange-700";
    }
    if (priorityLevel === "medium") {
      return "bg-sky-100 text-sky-700";
    }
    return "bg-slate-100 text-slate-700";
  };

  const priorityLabel = (priorityLevel: AdminInsightRow["priority_level"]) => {
    if (priorityLevel === "critical") {
      return "Critical priority";
    }
    if (priorityLevel === "high") {
      return "High priority";
    }
    if (priorityLevel === "medium") {
      return "Medium priority";
    }
    return "Low priority";
  };

  const columns: DataTableColumn<AdminInsightRow>[] = [
    {
      key: "user",
      label: "User",
      sortable: true,
      sortKey: "user_name",
      render: (insight) => (
        <div>
          <p className="font-medium text-slate-900">{insight.user_name}</p>
          <p className="text-slate-500">{insight.user_email}</p>
        </div>
      ),
    },
    {
      key: "title",
      label: "Insight",
      sortable: true,
      sortKey: "title",
      widthClassName: "min-w-[280px]",
      render: (insight) => (
        <div className="space-y-1">
          <p className="font-medium text-slate-900">{insight.title}</p>
          <p className="text-slate-500">{insight.message}</p>
          {insight.priority_reason ? <p className="text-xs text-slate-400">{insight.priority_reason}</p> : null}
        </div>
      ),
    },
    {
      key: "severity",
      label: "Severity",
      sortable: true,
      sortKey: "severity",
      render: (insight) => (
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
            insight.severity === "critical"
              ? "bg-rose-100 text-rose-700"
              : insight.severity === "warning"
                ? "bg-amber-100 text-amber-700"
                : "bg-emerald-100 text-emerald-700"
          }`}
        >
          {insight.severity}
        </span>
      ),
    },
    {
      key: "priority",
      label: "Priority",
      sortable: true,
      sortKey: "priority_score",
      render: (insight) =>
        insight.priority_level ? (
          <div className="space-y-1">
            <span
              className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${priorityBadgeClassName(
                insight.priority_level,
              )}`}
            >
              {priorityLabel(insight.priority_level)}
            </span>
          </div>
        ) : (
          <span className="text-slate-400">Unavailable</span>
        ),
    },
    {
      key: "period",
      label: "Period",
      sortable: true,
      sortKey: "period_start",
      render: (insight) => (
        <span className="text-slate-500">
          {formatDate(insight.period_start)} - {formatDate(insight.period_end)}
        </span>
      ),
    },
    {
      key: "created_at",
      label: "Created",
      sortable: true,
      sortKey: "created_at",
      render: (insight) => <span className="text-slate-500">{formatDateTime(insight.created_at)}</span>,
    },
  ];

  const data = table.data;
  const criticalCount = data?.severity_distribution.find((item) => item.label === "critical")?.count ?? 0;
  const warningCount = data?.severity_distribution.find((item) => item.label === "warning")?.count ?? 0;

  return (
    <AdminShell
      title="AI Insight Monitoring"
      description="Review generated insights across all users, inspect severity trends, and watch the most common triggers produced by the AI layer."
      actions={
        <button onClick={() => void Promise.all([table.refetch(), usersQuery.refetch()])} className="bg-white px-4 py-2 text-sm text-slate-700 shadow-sm ring-1 ring-slate-200">
          Refresh
        </button>
      }
    >
      <div className="space-y-6">
        {table.error && <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{table.error}</div>}

        {table.isLoading && !data ? (
          <BizMoneyLoader minHeightClassName="min-h-[24rem]" label="Loading AI insight monitoring" />
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-3">
              <AdminMetricCard label="Visible Insights" value={formatCompactNumber(table.total)} helper="Current filtered result set" />
              <AdminMetricCard label="Critical" value={formatCompactNumber(criticalCount)} helper="Highest severity insights" tone="danger" />
              <AdminMetricCard label="Warning" value={formatCompactNumber(warningCount)} helper="Potentially actionable insights" tone="warning" />
            </div>

            <div className="grid gap-6 xl:grid-cols-2">
              <AdminPanel title="Severity Summary" description="Distribution of all visible insights by severity.">
                {data?.severity_distribution.length ? (
                  <div className="h-80">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={data.severity_distribution} dataKey="count" nameKey="label" outerRadius={96} innerRadius={56}>
                          {data.severity_distribution.map((entry, index) => (
                            <Cell key={entry.label} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(value: number) => value.toLocaleString("en-US")} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">No severity data is available yet.</p>
                )}
              </AdminPanel>

              <AdminPanel title="Trigger Frequency" description="Most common insight titles generated by the AI rules.">
                {data?.trigger_frequency.length ? (
                  <div className="h-80">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={data.trigger_frequency.slice(0, 6)} layout="vertical" margin={{ left: 24 }}>
                        <XAxis type="number" tick={{ fontSize: 11 }} />
                        <YAxis type="category" dataKey="label" width={150} tick={{ fontSize: 11 }} />
                        <Tooltip />
                        <Bar dataKey="count" fill="#0f172a" radius={[0, 8, 8, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">No trigger frequency data is available yet.</p>
                )}
              </AdminPanel>
            </div>

            <AdminPanel title="Insight Table" description="Detailed review of each insight without exposing unnecessary financial record details.">
              <DataTable
                columns={columns}
                rows={table.rows}
                rowKey={(row) => row.insight_id}
                total={table.total}
                limit={table.limit}
                currentPage={table.currentPage}
                totalPages={table.totalPages}
                search={table.search}
                onSearchChange={table.setSearch}
                searchPlaceholder="Search titles, messages, or users"
                filters={filters}
                filterValues={table.filters}
                onFilterChange={table.setFilter}
                sortBy={table.sortBy}
                sortOrder={table.sortOrder}
                onSortChange={table.setSort}
                onPageChange={table.setPage}
                onPageSizeChange={table.setPageSize}
                emptyMessage="No insights matched the current filters."
                isLoading={table.isLoading}
                isFetching={table.isFetching || usersQuery.isFetching}
              />
            </AdminPanel>
          </>
        )}
      </div>
    </AdminShell>
  );
}
