"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type SystemStatus = {
  model: { provider: string; chat: string; build: string; review: string };
  database: { kind: string };
  slack_configured: boolean;
  github_configured: boolean;
  connectors: Record<string, boolean>;
  admins_count: number;
  advisories: { name: string; message: string }[];
};

export function useSystemStatus() {
  return useQuery({
    queryKey: ["system"],
    queryFn: () => api<SystemStatus>("/api/console/v1/system"),
  });
}

export function useReviewTrends(days = 30) {
  return useQuery({
    queryKey: ["review-trends", days],
    queryFn: () => api<{ by_week: Record<string, Record<string, number>> }>(`/api/console/v1/system/review-trends?days=${days}`),
    select: (d) => d.by_week,
  });
}
