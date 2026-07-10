"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

/**
 * Pending-approvals count for the nav badge. Admin-only endpoint — may 403 for
 * members; callers guard on role.
 */
export function useApprovalCount() {
  return useQuery({
    queryKey: ["approval-count"],
    queryFn: () => api<{ pending: number }>("/api/console/v1/approvals/count"),
    refetchInterval: 10_000,
  });
}
