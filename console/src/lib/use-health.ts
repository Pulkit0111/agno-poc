"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type HealthConnector = {
  name: string;
  ok: boolean;
  on?: string;
  off?: string;
  [key: string]: unknown;
};

export type Health = {
  model: { connected: boolean; provider: string };
  jobs: { running: number; queued: number; failed_24h: number };
  connectors: HealthConnector[];
  webhook: { last_received_at: number | null };
};

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => api<Health>("/api/console/v1/health"),
    refetchInterval: 15_000,
  });
}
