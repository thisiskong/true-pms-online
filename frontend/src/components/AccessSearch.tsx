import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { Button, cx, inputCls } from "./ui";

/** Access id (circuit number) search: navigates to /access/:accessid. Used in the header and on the lookup page. */
export function AccessSearch({ initial = "", className, compact }: { initial?: string; className?: string; compact?: boolean }) {
  const [v, setV] = useState(initial);
  const nav = useNavigate();
  useEffect(() => setV(initial), [initial]);
  return (
    <form role="search" className={cx("flex items-center gap-2", className)}
      onSubmit={(e) => {
        e.preventDefault();
        const id = v.replace(/\s+/g, "");
        if (id) nav(`/access/${encodeURIComponent(id)}`);
      }}>
      <input value={v} onChange={(e) => setV(e.target.value)} inputMode="numeric" aria-label="Access id"
        placeholder={compact ? "Access id…" : "Access id / circuit no., e.g. 9605163336"}
        className={cx(inputCls, "font-mono", compact ? "w-40" : "w-80")} />
      {!compact && <Button type="submit" variant="primary" className="shrink-0 whitespace-nowrap">Look up</Button>}
    </form>
  );
}
