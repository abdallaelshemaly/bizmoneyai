"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
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
import { formatCompactNumber, formatCurrency } from "@/lib/format";
import { AdminBudgetRow, AdminBudgetsResponse, AdminUsersResponse } from "@/lib/types";

export default function AdminBudgetsPage() {
  const usersQuery = useQuery({
    queryKey: ["admin-budget-user-options"],
    queryFn: async () => {
      const response = await api.get<AdminUsersResponse>("/admin/users", {
        params: { limit: 500, offset: 0, sort_by: "name", sort_order: "asc" },
      });
      return response.data.users;
    },
  });

  const table = useAdminDataTable<AdminBudgetsResponse, AdminBudgetRow>({
    queryKey: "admin-budgets",
    endpoint: "/admin/budgets",
    extractRows: (response) => response.budgets,
    extractTotal: (response) => response.total,
    initialFilters: { user_id: "", month: "" },
    initialLimit: 10,
    defaultSort: { key: "month", order: "desc" },
    errorMessage: "Failed to load budgets.",
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
    { key: "month", type: "month" },
  ];

  const columns: DataTableColumn<AdminBudgetRow>[] = [
    { key: "month", label: "Month", sortable: true, sortKey: "month", render: (budget) => <span className="text-slate-500">{budget.month}</span> },
    {
      key: "user",
      label: "User",
      sortable: true,
      sortKey: "user_name",
      render: (budget) => (
        <div>
          <p className="font-medium text-slate-900">{budget.user_name}</p>
          <p className="text-slate-500">{budget.user_email}</p>
        </div>
      ),
    },
    { key: "category_name", label: "Category", sortable: true, sortKey: "category_name", render: (budget) => <span className="text-slate-600">{budget.category_name}</span> },
    { key: "amount", label: "Budgeted", sortable: true, sortKey: "amount", align: "right", render: (budget) => <span className="text-slate-600">{formatCurrency(budget.amount)}</span> },
    { key: "spent", label: "Spent", sortable: true, sortKey: "spent", align: "right", render: (budget) => <span className="text-slate-600">{formatCurrency(budget.spent)}</span> },
    {
      key: "remaining",
      label: "Remaining",
      sortable: true,
      sortKey: "remaining",
      align: "right",
      render: (budget) => (
        <span className={`font-semibold ${budget.remaining < 0 ? "text-rose-600" : "text-slate-700"}`}>
          {formatCurrency(budget.remaining)}
        </span>
      ),
    },
    {
      key: "status",
      label: "Status",
      sortable: true,
      sortKey: "status",
      render: (budget) => (
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
            budget.status === "over"
              ? "bg-rose-100 text-rose-700"
              : budget.status === "near_limit"
                ? "bg-amber-100 text-amber-700"
                : "bg-emerald-100 text-emerald-700"
          }`}
        >
          {budget.status.replace("_", " ")}
        </span>
      ),
    },
  ];

  const data = table.data;
  const budgets = data?.budgets ?? [];

  return (
    <AdminShell
      title="Budget Monitoring"
      description="Watch overspending patterns, track budget adherence, and identify the categories and months that require intervention."
      actions={
        <button onClick={() => void Promise.all([table.refetch(), usersQuery.refetch()])} className="bg-white px-4 py-2 text-sm text-slate-700 shadow-sm ring-1 ring-slate-200">
          Refresh
        </button>
      }
    >
      <div className="space-y-6">
        {table.error && <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{table.error}</div>}

        <div className="grid gap-4 md:grid-cols-4">
          <AdminMetricCard
            label="Budgeted"
            value={formatCurrency(data?.overspending_analysis.total_budgeted ?? 0)}
            helper={`${formatCompactNumber(table.total)} budgets in view`}
          />
          <AdminMetricCard
            label="Spent"
            value={formatCurrency(data?.overspending_analysis.total_spent ?? 0)}
            helper="Expense spend linked to tracked budgets"
            tone="success"
          />
          <AdminMetricCard
            label="Over Budget"
            value={formatCompactNumber(data?.overspending_analysis.over_budget_count ?? 0)}
            helper={`${formatCompactNumber(data?.overspending_analysis.near_limit_count ?? 0)} near the limit`}
            tone="warning"
          />
          <AdminMetricCard
            label="Overspent"
            value={formatCurrency(data?.overspending_analysis.total_overspent ?? 0)}
            helper="Total amount above budgeted values"
            tone="danger"
          />
        </div>

        {table.isLoading && !data ? (
          <BizMoneyLoader minHeightClassName="min-h-[24rem]" label="Loading budget monitoring" />
        ) : (
          <>
            <div className="grid gap-6 xl:grid-cols-2">
              <AdminPanel title="Budget Trends" description="Monthly budgeted versus spent totals, with over-budget counts per period.">
                {data?.budget_trends.length ? (
                  <div className="h-80">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={data.budget_trends}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} />
                        <Tooltip formatter={(value: number) => formatCurrency(value)} />
                        <Legend />
                        <Line type="monotone" dataKey="total_budgeted" name="Budgeted" stroke="#0f172a" strokeWidth={2} />
                        <Line type="monotone" dataKey="total_spent" name="Spent" stroke="#14b8a6" strokeWidth={2} />
                        <Line type="monotone" dataKey="over_budget_count" name="Over budget count" stroke="#f97316" strokeWidth={2} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">No budget trend data is available yet.</p>
                )}
              </AdminPanel>

              <AdminPanel title="Popular Budget Categories" description="Categories most frequently used in budgets, ordered by spend influence.">
                {data?.popular_categories.length ? (
                  <div className="h-80">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={data.popular_categories} layout="vertical" margin={{ left: 24 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis type="number" tick={{ fontSize: 11 }} />
                        <YAxis type="category" dataKey="category_name" width={110} tick={{ fontSize: 11 }} />
                        <Tooltip formatter={(value: number) => formatCurrency(value)} />
                        <Bar dataKey="total_spent" name="Spent" fill="#0f172a" radius={[0, 8, 8, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">No popular category data is available yet.</p>
                )}
              </AdminPanel>
            </div>

            <AdminPanel title="Budget Table" description="Budget rows with overspending indicators and remaining balances.">
              <DataTable
                columns={columns}
                rows={budgets}
                rowKey={(row) => row.budget_id}
                total={table.total}
                limit={table.limit}
                currentPage={table.currentPage}
                totalPages={table.totalPages}
                search={table.search}
                onSearchChange={table.setSearch}
                searchPlaceholder="Search budgets by category, user, or note"
                filters={filters}
                filterValues={table.filters}
                onFilterChange={table.setFilter}
                sortBy={table.sortBy}
                sortOrder={table.sortOrder}
                onSortChange={table.setSort}
                onPageChange={table.setPage}
                onPageSizeChange={table.setPageSize}
                emptyMessage="No budgets matched the current filters."
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
