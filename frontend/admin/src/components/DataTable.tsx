"use client";

import { ReactNode } from "react";

import BizMoneyLoader from "@/components/BizMoneyLoader";
import { AdminSortOrder } from "@/lib/types";

export type DataTableColumn<Row> = {
  key: string;
  label: string;
  render: (row: Row) => ReactNode;
  sortable?: boolean;
  sortKey?: string;
  align?: "left" | "right" | "center";
  widthClassName?: string;
};

export type DataTableFilterOption = {
  label: string;
  value: string;
};

export type DataTableFilterConfig = {
  key: string;
  label?: string;
  type?: "select" | "text" | "date" | "month";
  placeholder?: string;
  options?: DataTableFilterOption[];
};

type DataTableProps<Row> = {
  columns: DataTableColumn<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string | number;
  total: number;
  limit: number;
  currentPage: number;
  totalPages: number;
  search: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder?: string;
  filters?: DataTableFilterConfig[];
  filterValues?: Record<string, string>;
  onFilterChange?: (key: string, value: string) => void;
  sortBy: string;
  sortOrder: AdminSortOrder;
  onSortChange: (key: string) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (value: number) => void;
  pageSizeOptions?: number[];
  emptyMessage: string;
  isLoading?: boolean;
  isFetching?: boolean;
};

function alignmentClasses(align: "left" | "right" | "center" = "left") {
  if (align === "right") {
    return "text-right";
  }
  if (align === "center") {
    return "text-center";
  }
  return "text-left";
}

export default function DataTable<Row>({
  columns,
  rows,
  rowKey,
  total,
  limit,
  currentPage,
  totalPages,
  search,
  onSearchChange,
  searchPlaceholder = "Search",
  filters = [],
  filterValues = {},
  onFilterChange,
  sortBy,
  sortOrder,
  onSortChange,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [10, 25, 50],
  emptyMessage,
  isLoading = false,
  isFetching = false,
}: DataTableProps<Row>) {
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 xl:flex-row xl:flex-wrap">
        <input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={searchPlaceholder}
          className="w-full min-w-[220px] bg-white xl:max-w-sm xl:flex-1"
        />

        {filters.map((filter) => {
          const value = filterValues[filter.key] ?? "";
          const inputClassName = "w-full min-w-[160px] bg-white xl:w-auto xl:flex-1";

          if (filter.type === "select") {
            return (
              <select
                key={filter.key}
                value={value}
                onChange={(event) => onFilterChange?.(filter.key, event.target.value)}
                className={inputClassName}
              >
                {(filter.options ?? []).map((option) => (
                  <option key={`${filter.key}-${option.value || "empty"}`} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            );
          }

          return (
            <input
              key={filter.key}
              type={filter.type === "month" ? "month" : filter.type === "date" ? "date" : "text"}
              value={value}
              placeholder={filter.placeholder}
              onChange={(event) => onFilterChange?.(filter.key, event.target.value)}
              className={inputClassName}
            />
          );
        })}

        <select
          value={String(limit)}
          onChange={(event) => onPageSizeChange(Number(event.target.value))}
          className="w-full min-w-[140px] bg-white xl:w-auto"
        >
          {pageSizeOptions.map((option) => (
            <option key={option} value={option}>
              {option} / page
            </option>
          ))}
        </select>
      </div>

      {isFetching && !isLoading && (
        <p className="text-sm font-medium text-teal-700">Updating table results...</p>
      )}

      {isLoading ? (
        <BizMoneyLoader minHeightClassName="min-h-56" label="Loading table data" />
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-400">{emptyMessage}</p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-[0.18em] text-slate-500">
                <tr>
                  {columns.map((column) => {
                    const activeSortKey = column.sortKey ?? column.key;
                    const isActive = sortBy === activeSortKey;
                    const isSortable = column.sortable ?? !!column.sortKey;

                    return (
                      <th
                        key={column.key}
                        className={`px-4 py-3 ${alignmentClasses(column.align)} ${column.widthClassName ?? ""}`}
                      >
                        {isSortable ? (
                          <button
                            type="button"
                            onClick={() => onSortChange(activeSortKey)}
                            className={`inline-flex items-center gap-2 bg-transparent px-0 py-0 text-xs uppercase tracking-[0.18em] ${isActive ? "text-slate-900" : "text-slate-500"
                              }`}
                          >
                            <span>{column.label}</span>
                            <span className="text-[10px]">{isActive ? (sortOrder === "asc" ? "↑" : "↓") : "↕"}</span>
                          </button>
                        ) : (
                          <span>{column.label}</span>
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={rowKey(row)} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/70"}>
                    {columns.map((column) => (
                      <td
                        key={`${rowKey(row)}-${column.key}`}
                        className={`px-4 py-4 align-top ${alignmentClasses(column.align)} ${column.widthClassName ?? ""}`}
                      >
                        {column.render(row)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-col gap-3 border-t border-slate-100 pt-4 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
            <span>
              Showing {rows.length === 0 ? 0 : (currentPage - 1) * limit + 1}
              {" - "}
              {(currentPage - 1) * limit + rows.length} of {total}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => onPageChange(currentPage - 1)}
                disabled={currentPage === 1}
                className="bg-slate-200 px-3 py-2 text-slate-700"
              >
                Previous
              </button>
              <span>
                Page {currentPage} of {totalPages}
              </span>
              <button
                onClick={() => onPageChange(currentPage + 1)}
                disabled={currentPage === totalPages}
                className="bg-slate-900 px-3 py-2 text-white"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
