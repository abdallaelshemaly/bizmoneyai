"use client";

import { FormEvent, useState } from "react";

import BizMoneyLoader from "@/components/BizMoneyLoader";
import AdminMetricCard from "@/components/AdminMetricCard";
import AdminPanel from "@/components/AdminPanel";
import AdminShell from "@/components/AdminShell";
import DataTable, { DataTableColumn, DataTableFilterConfig } from "@/components/DataTable";
import { useAdminDataTable } from "@/hooks/useAdminDataTable";
import api from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { formatCompactNumber, formatDateTime } from "@/lib/format";
import { AdminUserRow, AdminUsersResponse } from "@/lib/types";

type CreateUserForm = {
  name: string;
  email: string;
  password: string;
  is_active: boolean;
};

const initialCreateForm: CreateUserForm = {
  name: "",
  email: "",
  password: "",
  is_active: true,
};

export default function AdminUsersPage() {
  const table = useAdminDataTable<AdminUsersResponse, AdminUserRow>({
    queryKey: "admin-users",
    endpoint: "/admin/users",
    extractRows: (response) => response.users,
    extractTotal: (response) => response.total,
    initialFilters: { is_active: "" },
    initialLimit: 10,
    defaultSort: { key: "created_at", order: "desc" },
    errorMessage: "Failed to load users.",
  });

  const [actionError, setActionError] = useState("");
  const [busyUserId, setBusyUserId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<CreateUserForm>(initialCreateForm);
  const [createError, setCreateError] = useState("");
  const [createSuccess, setCreateSuccess] = useState("");
  const [createLoading, setCreateLoading] = useState(false);

  const createUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreateError("");
    setCreateSuccess("");

    if (createForm.password.length < 6) {
      setCreateError("Password must be at least 6 characters.");
      return;
    }

    setCreateLoading(true);
    try {
      const response = await api.post<AdminUserRow>("/admin/users", createForm);
      setCreateSuccess(`${response.data.email} was created.`);
      setCreateForm(initialCreateForm);
      await table.refetch();
    } catch (err: unknown) {
      setCreateError(getErrorMessage(err, "Failed to create the user."));
    } finally {
      setCreateLoading(false);
    }
  };

  const toggleStatus = async (user: AdminUserRow) => {
    setBusyUserId(user.user_id);
    setActionError("");
    try {
      await api.patch(`/admin/users/${user.user_id}/status`, {
        is_active: !user.is_active,
      });
      await table.refetch();
    } catch (err: unknown) {
      setActionError(getErrorMessage(err, "Failed to update the user status."));
    } finally {
      setBusyUserId(null);
    }
  };

  const deleteUser = async (user: AdminUserRow) => {
    if (!window.confirm(`Delete ${user.email}? This cannot be undone.`)) {
      return;
    }

    setBusyUserId(user.user_id);
    setActionError("");
    try {
      await api.delete(`/admin/users/${user.user_id}`);
      await table.refetch();
    } catch (err: unknown) {
      setActionError(getErrorMessage(err, "Failed to delete the user."));
    } finally {
      setBusyUserId(null);
    }
  };

  const filters: DataTableFilterConfig[] = [
    {
      key: "is_active",
      type: "select",
      options: [
        { label: "All statuses", value: "" },
        { label: "Active only", value: "true" },
        { label: "Inactive only", value: "false" },
      ],
    },
  ];

  const columns: DataTableColumn<AdminUserRow>[] = [
    {
      key: "user",
      label: "User",
      sortable: true,
      sortKey: "name",
      render: (user) => (
        <div>
          <p className="font-medium text-slate-900">{user.name}</p>
          <p className="text-slate-500">{user.email}</p>
          <p className="mt-1 text-xs text-slate-400">{user.insights_count} insights</p>
        </div>
      ),
    },
    {
      key: "status",
      label: "Status",
      sortable: true,
      sortKey: "is_active",
      render: (user) => (
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
            user.is_active ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"
          }`}
        >
          {user.is_active ? "Active" : "Inactive"}
        </span>
      ),
    },
    { key: "transactions", label: "Transactions", sortable: true, sortKey: "transactions_count", render: (user) => <span className="text-slate-600">{user.transactions_count}</span> },
    { key: "categories", label: "Categories", sortable: true, sortKey: "categories_count", render: (user) => <span className="text-slate-600">{user.categories_count}</span> },
    { key: "budgets", label: "Budgets", sortable: true, sortKey: "budgets_count", render: (user) => <span className="text-slate-600">{user.budgets_count}</span> },
    {
      key: "last_activity",
      label: "Last activity",
      sortable: true,
      sortKey: "last_activity",
      render: (user) => <span className="text-slate-500">{formatDateTime(user.last_activity)}</span>,
    },
    {
      key: "actions",
      label: "Actions",
      align: "right",
      render: (user) => (
        <div className="flex justify-end gap-2">
          <button
            onClick={() => void toggleStatus(user)}
            disabled={busyUserId === user.user_id}
            className={user.is_active ? "bg-amber-500 px-3 py-2 text-xs" : "bg-emerald-600 px-3 py-2 text-xs"}
          >
            {user.is_active ? "Deactivate" : "Activate"}
          </button>
          <button
            onClick={() => void deleteUser(user)}
            disabled={busyUserId === user.user_id}
            className="bg-rose-600 px-3 py-2 text-xs"
          >
            Delete
          </button>
        </div>
      ),
    },
  ];

  const usersSummary = table.data?.summary;
  const error = actionError || table.error;
  const isInitialLoading = table.isLoading && !table.data;

  return (
    <AdminShell
      title="User Monitoring"
      actions={
        <>
          <button onClick={() => setCreateOpen((open) => !open)} className="bg-emerald-600 px-4 py-2 text-sm">
            Create User
          </button>
          <button onClick={() => void table.refetch()} className="bg-white px-4 py-2 text-sm text-slate-700 shadow-sm ring-1 ring-slate-200">
            Refresh
          </button>
        </>
      }
    >
      {isInitialLoading ? (
        <BizMoneyLoader minHeightClassName="min-h-[28rem]" label="Loading user monitoring" />
      ) : (
      <div className="space-y-6">
        {error && <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        <div className="grid gap-4 md:grid-cols-3">
          <AdminMetricCard label="Users" value={formatCompactNumber(table.total)} helper="Loaded from current filters" />
          <AdminMetricCard label="Active" value={formatCompactNumber(usersSummary?.active_count ?? 0)} helper="Allowed to sign in" tone="success" />
          <AdminMetricCard label="Inactive" value={formatCompactNumber(usersSummary?.inactive_count ?? 0)} helper="Blocked from user auth" tone="warning" />
        </div>

        {createOpen && (
          <AdminPanel title="Create User">
            <form onSubmit={createUser} className="space-y-4">
              {createError && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{createError}</div>}
              {createSuccess && <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{createSuccess}</div>}

              <div className="grid gap-4 lg:grid-cols-[1fr_1fr_1fr_auto] lg:items-end">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Name</span>
                  <input
                    type="text"
                    value={createForm.name}
                    onChange={(event) => setCreateForm((form) => ({ ...form, name: event.target.value }))}
                    autoComplete="name"
                    placeholder="Jane Doe"
                    className="w-full"
                    required
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Email</span>
                  <input
                    type="email"
                    value={createForm.email}
                    onChange={(event) => setCreateForm((form) => ({ ...form, email: event.target.value }))}
                    autoComplete="email"
                    placeholder="user@company.com"
                    className="w-full"
                    required
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Password</span>
                  <input
                    type="password"
                    value={createForm.password}
                    onChange={(event) => setCreateForm((form) => ({ ...form, password: event.target.value }))}
                    autoComplete="new-password"
                    placeholder="Min 6 characters"
                    minLength={6}
                    className="w-full"
                    required
                  />
                </label>
                <div className="flex flex-wrap items-center gap-3">
                  <label className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={createForm.is_active}
                      onChange={(event) => setCreateForm((form) => ({ ...form, is_active: event.target.checked }))}
                      className="h-4 w-4"
                    />
                    Active
                  </label>
                  <button type="submit" disabled={createLoading} className="px-4 py-2 text-sm">
                    {createLoading ? "Creating..." : "Create"}
                  </button>
                </div>
              </div>
            </form>
          </AdminPanel>
        )}

        <AdminPanel title="Manage Users">
          <DataTable
            columns={columns}
            rows={table.rows}
            rowKey={(row) => row.user_id}
            total={table.total}
            limit={table.limit}
            currentPage={table.currentPage}
            totalPages={table.totalPages}
            search={table.search}
            onSearchChange={table.setSearch}
            searchPlaceholder="Search users by name or email"
            filters={filters}
            filterValues={table.filters}
            onFilterChange={table.setFilter}
            sortBy={table.sortBy}
            sortOrder={table.sortOrder}
            onSortChange={table.setSort}
            onPageChange={table.setPage}
            onPageSizeChange={table.setPageSize}
            emptyMessage="No users matched the current filters."
            isLoading={table.isLoading}
            isFetching={table.isFetching}
          />
        </AdminPanel>
      </div>
      )}
    </AdminShell>
  );
}
