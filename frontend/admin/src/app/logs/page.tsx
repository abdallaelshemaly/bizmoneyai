"use client";

import BizMoneyLoader from "@/components/BizMoneyLoader";
import AdminMetricCard from "@/components/AdminMetricCard";
import AdminPanel from "@/components/AdminPanel";
import AdminShell from "@/components/AdminShell";
import DataTable, { DataTableColumn, DataTableFilterConfig } from "@/components/DataTable";
import { useAdminDataTable } from "@/hooks/useAdminDataTable";
import { formatCompactNumber, formatDateTime } from "@/lib/format";
import { AdminLogRow, AdminLogsResponse } from "@/lib/types";

const EVENT_TYPE_OPTIONS = [
  "admin_login",
  "create_budget",
  "create_category",
  "create_transaction",
  "delete_transaction",
  "delete_category",
  "delete_user",
  "disable_user",
  "enable_user",
  "generate_insights",
  "import_transactions",
  "unusual_transaction_detected",
  "update_transaction",
  "update_budget",
  "user_login",
  "user_registration",
];

function formatMetadataValue(value: unknown) {
  if (value === null) {
    return "null";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function AuditMetadata({ metadata }: { metadata: AdminLogRow["metadata"] }) {
  if (!metadata || Object.keys(metadata).length === 0) {
    return <span className="text-slate-400">No metadata</span>;
  }

  return (
    <div className="flex min-w-[240px] flex-wrap gap-2">
      {Object.entries(metadata).map(([key, value]) => (
        <span key={key} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">
          <span className="font-semibold text-slate-700">{key}:</span> {formatMetadataValue(value)}
        </span>
      ))}
    </div>
  );
}

export default function AdminLogsPage() {
  const table = useAdminDataTable<AdminLogsResponse, AdminLogRow>({
    queryKey: "admin-logs",
    endpoint: "/admin/logs",
    extractRows: (response) => response.logs,
    extractTotal: (response) => response.total,
    initialFilters: {
      event_type: "",
      level: "",
      date_from: "",
      date_to: "",
    },
    initialLimit: 10,
    defaultSort: { key: "created_at", order: "desc" },
    errorMessage: "Failed to load system logs.",
  });

  const filters: DataTableFilterConfig[] = [
    {
      key: "event_type",
      type: "select",
      options: [
        { label: "All events", value: "" },
        ...EVENT_TYPE_OPTIONS.map((eventType) => ({
          label: eventType,
          value: eventType,
        })),
      ],
    },
    {
      key: "level",
      type: "select",
      options: [
        { label: "All levels", value: "" },
        { label: "Info", value: "info" },
        { label: "Warning", value: "warning" },
        { label: "Error", value: "error" },
        { label: "Critical", value: "critical" },
      ],
    },
    { key: "date_from", type: "date" },
    { key: "date_to", type: "date" },
  ];

  const columns: DataTableColumn<AdminLogRow>[] = [
    {
      key: "created_at",
      label: "Created",
      sortable: true,
      sortKey: "created_at",
      render: (log) => <span className="text-slate-500">{formatDateTime(log.created_at)}</span>,
    },
    {
      key: "event_type",
      label: "Event",
      sortable: true,
      sortKey: "event_type",
      render: (log) => <span className="font-medium text-slate-900">{log.event_type}</span>,
    },
    {
      key: "level",
      label: "Level",
      sortable: true,
      sortKey: "level",
      render: (log) => (
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
      ),
    },
    {
      key: "actor",
      label: "Linked actor",
      render: (log) => (
        <div className="text-slate-600">
          <p>{log.admin_name || log.user_name || "System"}</p>
          <p className="text-xs text-slate-400">{log.admin_email || log.user_email || "background process"}</p>
        </div>
      ),
    },
    {
      key: "message",
      label: "Message",
      sortable: true,
      sortKey: "message",
      widthClassName: "min-w-[320px]",
      render: (log) => <span className="text-slate-500">{log.message}</span>,
    },
    {
      key: "metadata",
      label: "Metadata",
      widthClassName: "min-w-[280px]",
      render: (log) => <AuditMetadata metadata={log.metadata} />,
    },
  ];

  const summary = table.data?.summary;
  const isInitialLoading = table.isLoading && !table.data;

  return (
    <AdminShell
      title="System Logs"
      description="Inspect operational events captured by the system log table without exposing unnecessary transaction-level detail."
      actions={
        <button onClick={() => void table.refetch()} className="bg-white px-4 py-2 text-sm text-slate-700 shadow-sm ring-1 ring-slate-200">
          Refresh
        </button>
      }
    >
      {isInitialLoading ? (
        <BizMoneyLoader minHeightClassName="min-h-[28rem]" label="Loading system logs" />
      ) : (
      <div className="space-y-6">
        {table.error && <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{table.error}</div>}

        <div className="grid gap-4 md:grid-cols-3">
          <AdminMetricCard label="Visible Logs" value={formatCompactNumber(table.total)} helper="Filtered result set" />
          <AdminMetricCard label="Warnings" value={formatCompactNumber(summary?.warning_count ?? 0)} helper="Operational alerts" tone="warning" />
          <AdminMetricCard label="Errors" value={formatCompactNumber(summary?.error_count ?? 0)} helper="Higher-severity failures" tone="danger" />
        </div>

        <AdminPanel title="Log Table" description="Recent system events with linked admin or user context when available.">
          <DataTable
            columns={columns}
            rows={table.rows}
            rowKey={(row) => row.log_id}
            total={table.total}
            limit={table.limit}
            currentPage={table.currentPage}
            totalPages={table.totalPages}
            search={table.search}
            onSearchChange={table.setSearch}
            searchPlaceholder="Search logs, actors, or messages"
            filters={filters}
            filterValues={table.filters}
            onFilterChange={table.setFilter}
            sortBy={table.sortBy}
            sortOrder={table.sortOrder}
            onSortChange={table.setSort}
            onPageChange={table.setPage}
            onPageSizeChange={table.setPageSize}
            emptyMessage="No logs matched the current filters."
            isLoading={table.isLoading}
            isFetching={table.isFetching}
          />
        </AdminPanel>
      </div>
      )}
    </AdminShell>
  );
}
