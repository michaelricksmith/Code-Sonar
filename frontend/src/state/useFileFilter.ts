import { useCallback, useState } from "react";

export function useFileFilter() {
  const [fileFilter, setFileFilter] = useState<string | null>(null);
  const clear = useCallback(() => setFileFilter(null), []);
  return { fileFilter, setFileFilter, clear };
}