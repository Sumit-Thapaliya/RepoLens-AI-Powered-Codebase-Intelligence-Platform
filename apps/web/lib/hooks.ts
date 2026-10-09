"use client";

import * as React from "react";
import useSWR, { type SWRResponse } from "swr";
import { ApiError } from "./api";

/**
 * Thin SWR wrapper with the project defaults: no polling unless asked for,
 * request deduplication, retry only on transport errors (not 4xx).
 */
export function useApi<T>(key: string | null | ((id: string) => string), fetcher: () => Promise<T>, options: { refreshInterval?: number; revalidateOnFocus?: boolean } = {}): SWRResponse<T, ApiError> {
  const resolvedKey = typeof key === "function" ? key("") : key;
  return useSWR<T, ApiError>(resolvedKey, fetcher, {
    revalidateOnFocus: options.revalidateOnFocus ?? false,
    refreshInterval: options.refreshInterval,
    shouldRetryOnError: (error) => error instanceof ApiError && error.status >= 500,
    errorRetryCount: 2,
    keepPreviousData: true,
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
