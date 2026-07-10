"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type ActivityJob = {
  id: number;
  kind: string;
  status: string;
  created: number;
  user_id?: string;
  args?: string;
};

/**
 * Admin live feed of recent jobs across all users. Separate from useJobs so its
 * fast (5s) poll doesn't affect the shared jobs cache.
 */
export function useActivity() {
  return useQuery({
    queryKey: ["activity"],
    queryFn: () =>
      api<{ jobs: ActivityJob[] }>("/api/console/v1/jobs?scope=all&limit=50"),
    refetchInterval: 5_000,
  });
}
