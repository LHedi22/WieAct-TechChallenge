// Admin data hooks and helpers (kept out of component files for fast refresh).
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { adminCall } from "./adminApi";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type Filters = Record<string, string>;

export function qs(params: Record<string, string | number | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function usePaged<T>(path: string, filters: Filters, page: number) {
  return useQuery({
    queryKey: ["admin", path, filters, page],
    queryFn: () => adminCall<Page<T>>(`${path}${qs({ ...filters, page })}`),
    placeholderData: keepPreviousData,
  });
}
