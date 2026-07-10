"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type JobCounts = {
  running: number;
  queued: number;
  done: number;
  failed: number;
  failed_24h: number;
};

export function useJobCounts() {
  return useQuery({
    queryKey: ["job-counts"],
    queryFn: () => api<JobCounts>("/api/console/v1/jobs/counts"),
    refetchInterval: 10_000,
  });
}
