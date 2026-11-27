import type { FacetValue } from "../api/types";
import { cx, Field, inputCls } from "./ui";

/** Device-filter dropdown fed by /api/devices/facets. */
export function FacetSelect({ name, value, options, onChange, loading, sortByName, showCounts = true }: {
  name: string; value: string; options: FacetValue[] | undefined; onChange: (v: string) => void; loading?: boolean; sortByName?: boolean;
  /** false where the counts would mislead (they are inventory counts, not counts of the page's rows). */
  showCounts?: boolean;
}) {
  // Counts reflect all OTHER active filters. Keep the current selection listed even if it now has 0 matches.
  const opts = sortByName
    ? [...(options ?? [])].sort((a, b) => String(a.value).localeCompare(String(b.value), undefined, { numeric: true, sensitivity: "base" }))
    : (options ?? []);
  const list = value && !opts.some((o) => String(o.value) === value) ? [{ value, count: 0 }, ...opts] : opts;
  return (
    <Field label={name}>
      <select className={cx(inputCls, loading && "text-zinc-400")} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {list.map((o) => (
          <option key={String(o.value)} value={String(o.value)}>{String(o.value)}{showCounts ? ` (${o.count.toLocaleString()})` : ""}</option>
        ))}
      </select>
    </Field>
  );
}
