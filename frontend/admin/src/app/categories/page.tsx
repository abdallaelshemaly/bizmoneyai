"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import BizMoneyLoader from "@/components/BizMoneyLoader";
import AdminMetricCard from "@/components/AdminMetricCard";
import AdminPanel from "@/components/AdminPanel";
import AdminShell from "@/components/AdminShell";
import DataTable, { DataTableColumn, DataTableFilterConfig } from "@/components/DataTable";
import { useAdminDataTable } from "@/hooks/useAdminDataTable";
import api from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { formatCompactNumber, formatDateTime } from "@/lib/format";
import {
  AdminCategoriesResponse,
  AdminCategoryRow,
  AdminDefaultCategoriesResult,
  AdminUsersResponse,
} from "@/lib/types";

export default function AdminCategoriesPage() {
  const usersQuery = useQuery({
    queryKey: ["admin-category-user-options"],
    queryFn: async () => {
      const response = await api.get<AdminUsersResponse>("/admin/users", {
        params: { limit: 500, offset: 0, sort_by: "name", sort_order: "asc" },
      });
      return response.data.users;
    },
  });

  const table = useAdminDataTable<AdminCategoriesResponse, AdminCategoryRow>({
    queryKey: "admin-categories",
    endpoint: "/admin/categories",
    extractRows: (response) => response.categories,
    extractTotal: (response) => response.total,
    initialFilters: { user_id: "", type: "" },
    initialLimit: 10,
    defaultSort: { key: "created_at", order: "desc" },
    errorMessage: "Failed to load categories.",
  });

  const [actionError, setActionError] = useState("");
  const [success, setSuccess] = useState("");
  const [busyCategoryId, setBusyCategoryId] = useState<number | null>(null);
  const [defaultsBusy, setDefaultsBusy] = useState(false);

  const createDefaults = async () => {
    setDefaultsBusy(true);
    setActionError("");
    setSuccess("");
    try {
      const response = await api.post<AdminDefaultCategoriesResult>("/admin/categories/defaults", null, {
        params: { user_id: table.filters.user_id || undefined },
      });
      setSuccess(`Created ${response.data.created_count} missing default categories.`);
      await Promise.all([table.refetch(), usersQuery.refetch()]);
    } catch (err: unknown) {
      setActionError(getErrorMessage(err, "Failed to create default categories."));
    } finally {
      setDefaultsBusy(false);
    }
  };

  const deleteCategory = async (category: AdminCategoryRow) => {
    if (!window.confirm(`Delete category "${category.name}"? Linked budgets and transactions will be removed.`)) {
      return;
    }

    setBusyCategoryId(category.category_id);
    setActionError("");
    setSuccess("");
    try {
      await api.delete(`/admin/categories/${category.category_id}`);
      await table.refetch();
    } catch (err: unknown) {
      setActionError(getErrorMessage(err, "Failed to delete category."));
    } finally {
      setBusyCategoryId(null);
    }
  };

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
      key: "type",
      type: "select",
      options: [
        { label: "All category types", value: "" },
        { label: "Income", value: "income" },
        { label: "Expense", value: "expense" },
        { label: "Both", value: "both" },
      ],
    },
  ];

  const columns: DataTableColumn<AdminCategoryRow>[] = [
    {
      key: "name",
      label: "Category",
      sortable: true,
      sortKey: "name",
      render: (category) => (
        <div>
          <p className="font-medium text-slate-900">{category.name}</p>
          <p className="text-xs text-slate-400">ID {category.category_id}</p>
        </div>
      ),
    },
    {
      key: "owner",
      label: "Owner",
      sortable: true,
      sortKey: "user_name",
      render: (category) => (
        <div>
          <p className="font-medium text-slate-900">{category.user_name}</p>
          <p className="text-slate-500">{category.user_email}</p>
        </div>
      ),
    },
    {
      key: "type",
      label: "Type",
      sortable: true,
      sortKey: "type",
      render: (category) => (
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold uppercase text-slate-700">
          {category.type}
        </span>
      ),
    },
    { key: "transactions_count", label: "Transactions", sortable: true, sortKey: "transactions_count", render: (category) => <span className="text-slate-600">{category.transactions_count}</span> },
    { key: "budgets_count", label: "Budgets", sortable: true, sortKey: "budgets_count", render: (category) => <span className="text-slate-600">{category.budgets_count}</span> },
    {
      key: "created_at",
      label: "Created",
      sortable: true,
      sortKey: "created_at",
      render: (category) => <span className="text-slate-500">{formatDateTime(category.created_at)}</span>,
    },
    {
      key: "actions",
      label: "Actions",
      align: "right",
      render: (category) => (
        <button
          onClick={() => void deleteCategory(category)}
          disabled={busyCategoryId === category.category_id}
          className="bg-rose-600 px-3 py-2 text-xs"
        >
          Delete
        </button>
      ),
    },
  ];

  const summary = table.data?.summary;
  const error = actionError || table.error;
  const isInitialLoading = table.isLoading && !table.data;

  return (
    <AdminShell
      title="Category Administration"
      description="Review category ownership, clean up inappropriate entries, and seed missing default categories for one user or the entire platform."
      actions={
        <>
          <button
            onClick={() => void createDefaults()}
            disabled={defaultsBusy}
            className="bg-emerald-600 px-4 py-2 text-sm"
          >
            {defaultsBusy ? "Creating..." : table.filters.user_id ? "Create Defaults For Selected User" : "Create Defaults For All Users"}
          </button>
          <button onClick={() => void Promise.all([table.refetch(), usersQuery.refetch()])} className="bg-white px-4 py-2 text-sm text-slate-700 shadow-sm ring-1 ring-slate-200">
            Refresh
          </button>
        </>
      }
    >
      {isInitialLoading ? (
        <BizMoneyLoader minHeightClassName="min-h-[28rem]" label="Loading category administration" />
      ) : (
      <div className="space-y-6">
        {error && <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
        {success && <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{success}</div>}

        <div className="grid gap-4 md:grid-cols-4">
          <AdminMetricCard label="Visible Categories" value={formatCompactNumber(table.total)} helper="Current filtered set" />
          <AdminMetricCard label="Expense Types" value={formatCompactNumber(summary?.expense_count ?? 0)} helper="Expense-only categories" tone="warning" />
          <AdminMetricCard label="Income Types" value={formatCompactNumber(summary?.income_count ?? 0)} helper="Income-only categories" tone="success" />
          <AdminMetricCard label="Both Types" value={formatCompactNumber(summary?.both_count ?? 0)} helper="Shared categories" />
        </div>

        <AdminPanel title="Category Table" description="Moderate the category catalogue and watch where category complexity is building up.">
          <DataTable
            columns={columns}
            rows={table.rows}
            rowKey={(row) => row.category_id}
            total={table.total}
            limit={table.limit}
            currentPage={table.currentPage}
            totalPages={table.totalPages}
            search={table.search}
            onSearchChange={table.setSearch}
            searchPlaceholder="Search categories, users, or email"
            filters={filters}
            filterValues={table.filters}
            onFilterChange={table.setFilter}
            sortBy={table.sortBy}
            sortOrder={table.sortOrder}
            onSortChange={table.setSort}
            onPageChange={table.setPage}
            onPageSizeChange={table.setPageSize}
            emptyMessage="No categories matched the current filters."
            isLoading={table.isLoading}
            isFetching={table.isFetching || usersQuery.isFetching}
          />
        </AdminPanel>
      </div>
      )}
    </AdminShell>
  );
}
