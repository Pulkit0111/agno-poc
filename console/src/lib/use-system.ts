"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type Advisory = { name: string; message: string };

/**
 * Admin-only advisories list (unconfigured connectors, disconnected Codex, etc).
 * Lives only on GET /v1/system — /v1/health doesn't carry it — so this hook
 * points there and selects out just the advisories, leaving the rest of that
 * richer payload unused for now.
 */
export function useAdvisories() {
  return useQuery({
    queryKey: ["system-advisories"],
    queryFn: () => api<{ advisories: Advisory[] }>("/api/console/v1/system"),
    select: (d) => d.advisories,
  });
}

export function useReviewTrends(days = 30) {
  return useQuery({
    queryKey: ["review-trends", days],
    queryFn: () => api<{ by_week: Record<string, Record<string, number>> }>(`/api/console/v1/system/review-trends?days=${days}`),
    select: (d) => d.by_week,
  });
}
