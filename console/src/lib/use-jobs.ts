"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Job } from "./types";

export function useJobs(scope: "mine" | "all" = "mine", limit = 25) {
  return useQuery({
    queryKey: ["jobs", scope, limit],
    queryFn: () => api<{ jobs: Job[] }>(`/api/console/v1/jobs?scope=${scope}&limit=${limit}`),
    refetchInterval: 10_000,
    select: (d) => d.jobs,
  });
}

export function useJob(id: number | null) {
  return useQuery({
    queryKey: ["job", id],
    queryFn: () => api<Job>(`/api/console/v1/jobs/${id}`),
    enabled: id !== null,
  });
}
