import { useEffect, useState } from "react";

/** Debounced text input bound to one URL param. */
export function useDraft(value: string, commit: (v: string) => void) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    if (draft === value) return;
    const t = setTimeout(() => commit(draft), 400);
    return () => clearTimeout(t);
  }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps
  return [draft, setDraft] as const;
}
