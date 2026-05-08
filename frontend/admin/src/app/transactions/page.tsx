"use client";

import { useQuery } from "@tanstack/react-query";

import AdminMetricCard from "@/components/AdminMetricCard";
import AdminPanel from "@/components/AdminPanel";
import AdminShell from "@/components/AdminShell";
import DataTable, { DataTableColumn, DataTableFilterConfig } from "@/components/DataTable";
import { useAdminDataTable } from "@/hooks/useAdminDataTable";
import api from "@/lib/api";
import { formatCompactNumber, formatCurrency, formatDate } from "@/lib/format";
import {
  AdminCategoriesResponse,
  AdminCategoryRow,
  AdminTransactionRow,
  AdminTransactionsResponse,
  AdminUsersResponse,
} from "@/lib/types";

const RISK_BADGE = {
  warning: "bg-amber-100 text-amber-700",
  critical: "bg-rose-100 text-rose-700",
};

export default function AdminTransactionsPage() {
  const usersQuery = useQuery({
    queryKey: ["admin-transaction-user-options"],
    queryFn: async () => {
      const response = await api.get<AdminUsersResponse>("/admin/users", {
        params: { limit: 500, offset: 0, sort_by: "name", sort_order: "asc" },
      });
      return response.data.users;
    },
  });

  const categoriesQuery = useQuery({
    queryKey: ["admin-transaction-category-options"],
    queryFn: async () => {
      const response = await api.get<AdminCategoriesResponse>("/admin/categories", {
        params: { limit: 500, offset: 0, sort_by: "name", sort_order: "asc" },
      });
      return response.data.categories;
    },
  });

  const table = useAdminDataTable<AdminTransactionsResponse, AdminTransactionRow>({
    queryKey: "admin-transactions",
    endpoint: "/admin/transactions",
    extractRows: (response) => response.transactions,
    extractTotal: (response) => response.total,
    initialFilters: {
      user_id: "",
      category_id: "",
      type: "",
      date_from: "",
      date_to: "",
    },
    initialLimit: 10,
    defaultSort: { key: "date", order: "desc" },
    errorMessage: "Failed to load transactions.",
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
      key: "category_id",
      type: "select",
      options: [
        { label: "All categories", value: "" },
        ...(categoriesQuery.data ?? []).map((category: AdminCategoryRow) => ({
          label: category.name,
          value: String(category.category_id),
        })),
      ],
    },
    {
      key: "type",
      type: "select",
      options: [
        { label: "All types", value: "" },
        { label: "Income", value: "income" },
        { label: "Expense", value: "expense" },
      ],
    },
    { key: "date_from", type: "date" },
    { key: "date_to", type: "date" },
  ];

  const columns: DataTableColumn<AdminTransactionRow>[] = [
    {
      key: "date",
      label: "Date",
      sortable: true,
      sortKey: "date",
      render: (transaction) => <span className="text-slate-500">{formatDate(transaction.date)}</span>,
    },
    {
      key: "user",
      label: "User",
      sortable: true,
      sortKey: "user_name",
      render: (transaction) => (
        <div>
          <p className="font-medium text-slate-900">{transaction.user_name}</p>
          <p className="text-slate-500">{transaction.user_email}</p>
        </div>
      ),
    },
    {
      key: "category_name",
      label: "Category",
      sortable: true,
      sortKey: "category_name",
      render: (transaction) => <span className="text-slate-600">{transaction.category_name}</span>,
    },
    {
      key: "type",
      label: "Type",
      sortable: true,
      sortKey: "type",
      render: (transaction) => (
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
            transaction.type === "income" ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"
          }`}
        >
          {transaction.type}
        </span>
      ),
    },
    {
      key: "description",
      label: "Description",
      sortable: true,
      sortKey: "description",
      widthClassName: "min-w-[260px]",
      render: (transaction) => <span className="text-slate-500">{transaction.description || "No description"}</span>,
    },
    {
      key: "amount",
      label: "Amount",
      sortable: true,
      sortKey: "amount",
      align: "right",
      render: (transaction) => (
        <span className={`font-semibold ${transaction.type === "income" ? "text-emerald-600" : "text-rose-600"}`}>
          {formatCurrency(transaction.amount)}
        </span>
      ),
    },
    {
      key: "fraud_risk_level",
      label: "Risk",
      render: (transaction) =>
        transaction.fraud_risk_level ? (
          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${RISK_BADGE[transaction.fraud_risk_level]}`}>
            {transaction.fraud_risk_level === "critical" ? "Critical" : "Unusual"}
            {transaction.fraud_probability !== null ? ` ${(transaction.fraud_probability * 100).toFixed(0)}%` : ""}
          </span>
        ) : (
          <span className="text-xs text-slate-400">No alert</span>
        ),
    },
  ];

  const summary = table.data?.summary;

  return (
    <AdminShell
      title="Transaction Monitoring"
      description="Review all recorded transactions across the platform with filters for user, category, type, and date range."
      actions={
        <button onClick={() => void Promise.all([table.refetch(), usersQuery.refetch(), categoriesQuery.refetch()])} className="bg-white px-4 py-2 text-sm text-slate-700 shadow-sm ring-1 ring-slate-200">
          Refresh
        </button>
      }
    >
      <div className="space-y-6">
        {table.error && <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{table.error}</div>}

        <div className="grid gap-4 md:grid-cols-4">
          <AdminMetricCard label="Visible Transactions" value={formatCompactNumber(table.total)} helper="Current filtered result set" />
          <AdminMetricCard label="Transaction Volume" value={formatCurrency(summary?.total_amount ?? 0)} helper="Combined amount across filters" tone="success" />
          <AdminMetricCard label="Income Rows" value={formatCompactNumber(summary?.income_count ?? 0)} helper="Read-only monitoring" />
          <AdminMetricCard label="Expense Rows" value={formatCompactNumber(summary?.expense_count ?? 0)} helper="Useful for anomaly review" tone="warning" />
        </div>

        <AdminPanel title="Transaction Table" description="A full read-only ledger view for operational review.">
          <DataTable
            columns={columns}
            rows={table.rows}
            rowKey={(row) => row.transaction_id}
            total={table.total}
            limit={table.limit}
            currentPage={table.currentPage}
            totalPages={table.totalPages}
            search={table.search}
            onSearchChange={table.setSearch}
            searchPlaceholder="Search description, user, or category"
            filters={filters}
            filterValues={table.filters}
            onFilterChange={table.setFilter}
            sortBy={table.sortBy}
            sortOrder={table.sortOrder}
            onSortChange={table.setSort}
            onPageChange={table.setPage}
            onPageSizeChange={table.setPageSize}
            emptyMessage="No transactions matched the current filters."
            isLoading={table.isLoading}
            isFetching={table.isFetching || usersQuery.isFetching || categoriesQuery.isFetching}
          />
        </AdminPanel>
      </div>
    </AdminShell>
  );
}
