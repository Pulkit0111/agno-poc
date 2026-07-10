"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";
import type { Approval } from "./types";

export function useApprovals(scope: "mine" | "all" = "mine") {
  return useQuery({
    queryKey: ["approvals", scope],
    queryFn: () => api<{ approvals: Approval[] }>(`/api/console/v1/approvals?scope=${scope}`),
    refetchInterval: 10_000,
    select: (d) => d.approvals,
  });
}

/**
 * Decision response. `job_id` is present for build/triage approvals (something
 * to watch run), absent for api approvals — consumers use it to link to the run.
 */
export type DecisionResult = { status: "approved" | "dismissed" | string; job_id?: number };

export function useDecide() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) =>
      api<DecisionResult>(`/api/console/v1/approvals/${id}/decision`, {
        method: "POST",
        body: JSON.stringify({ approve }),
      }),
    onMutate: async ({ id }) => {
      await qc.cancelQueries({ queryKey: ["approvals"] });
      const prev = qc.getQueriesData<{ approvals: Approval[] }>({ queryKey: ["approvals"] });
      qc.setQueriesData<{ approvals: Approval[] }>({ queryKey: ["approvals"] }, (d) =>
        d ? { approvals: d.approvals.filter((a) => a.id !== id) } : d,
      );
      return { prev };
    },
    onError: (err, _vars, ctx) => {
      ctx?.prev.forEach(([key, data]) => qc.setQueryData(key, data));
      toast.error(err instanceof ApiError ? err.message : "Couldn't record the decision.");
    },
    onSuccess: (res) => {
      if (res.status === "approved") {
        // Link the toast to where the run shows up (the admin live feed).
        toast.success("Approved — running it now", {
          action: { label: "View run", onClick: () => { window.location.href = "/activity"; } },
        });
      } else {
        toast.success("Dismissed.");
      }
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
  });
}
