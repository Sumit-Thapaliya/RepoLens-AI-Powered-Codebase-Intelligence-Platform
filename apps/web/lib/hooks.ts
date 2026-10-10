"use client";

import * as React from "react";
import useSWR, { type SWRResponse } from "swr";
import { ApiError } from "./api";

/**
 * Thin SWR wrapper with the project defaults: no polling unless asked for,
 * request deduplication, retry only on transport errors (not 4xx).
 */
export function useApi<T>(
  key: string | null,
  fetcher: () => Promise<T>,
  options: { refreshInterval?: number; revalidateOnFocus?: boolean; keepPreviousData?: boolean } = {},
): SWRResponse<T, ApiError> {
  return useSWR<T, ApiError>(key, fetcher, {
    revalidateOnFocus: options.revalidateOnFocus ?? false,
    refreshInterval: options.refreshInterval,
    shouldRetryOnError: (error) => error instanceof ApiError && error.status >= 500,
    errorRetryCount: 2,
    // Never flash another analysis's cached payload when the active id changes.
    keepPreviousData: options.keepPreviousData ?? false,
  });
}

export function useCapabilities() {
  return useSWR<Awaited<ReturnType<typeof import("./api").getCapabilities>>, ApiError>("capabilities", async () => {
    const { getCapabilities } = await import("./api");
    return getCapabilities();
  }, { revalidateOnFocus: false, shouldRetryOnError: false });
}

/** Format a byte size for the code viewer / tree. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
