import type { ReactNode } from "react";
import { cx, Empty, Spinner } from "./ui";

export interface Column<T> {
  key: string;
  header: string;
  sortable?: boolean;
  render?: (row: T) => ReactNode;
  className?: string;
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  sort?: string;
  order?: "asc" | "desc";
  onSort?: (key: string) => void;
  onRowClick?: (row: T) => void;
  loading?: boolean;
  empty?: ReactNode;
  dense?: boolean;
}

export function DataTable<T>({ columns, rows, rowKey, sort, order, onSort, onRowClick, loading, empty, dense }: Props<T>) {
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-zinc-200">
            {columns.map((c) => {
              const active = sort === c.key;
              return (
                <th key={c.key} scope="col"
                  className={cx("whitespace-nowrap px-3 py-2 text-left text-xs font-medium text-zinc-500", c.className)}
                  aria-sort={active ? (order === "asc" ? "ascending" : "descending") : undefined}>
                  {c.sortable && onSort ? (
                    <button type="button" onClick={() => onSort(c.key)}
                      className={cx("inline-flex items-center gap-1 hover:text-zinc-800", active && "text-zinc-900")}>
                      {c.header}
                      <span className={cx("text-[10px]", !active && "opacity-0")}>{order === "desc" ? "▼" : "▲"}</span>
                    </button>
                  ) : c.header}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className={cx(loading && "opacity-50 transition-opacity")}>
          {rows.map((r) => (
            <tr key={rowKey(r)} onClick={onRowClick ? () => onRowClick(r) : undefined}
              className={cx("border-b border-zinc-100 last:border-0", onRowClick && "cursor-pointer hover:bg-brand-50/50")}>
              {columns.map((c) => (
                <td key={c.key} className={cx("whitespace-nowrap px-3", dense ? "py-1.5" : "py-2", c.className)}>
                  {c.render ? c.render(r) : String((r as Record<string, unknown>)[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!loading && rows.length === 0 && <Empty>{empty ?? "No rows"}</Empty>}
      {loading && rows.length === 0 && <div className="flex justify-center py-10"><Spinner className="size-6" /></div>}
    </div>
  );
}
