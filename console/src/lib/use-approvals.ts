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

export function useDecide() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) =>
      api<{ status: string }>(`/api/console/v1/approvals/${id}/decision`, {
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
    onSuccess: (res) => toast.success(res.status === "approved" ? "Approved — running it now." : "Dismissed."),
    onSettled: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
  });
}
