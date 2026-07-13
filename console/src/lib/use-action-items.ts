"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type ActionItemSource = "user" | "dsm" | "console";

export type ActionItem = {
  id: number; user_id: string; text: string; status: string;
  remind_at: number | null; source: ActionItemSource; created: number; updated: number;
};

export function useActionItems(includeDone = false) {
  return useQuery({
    queryKey: ["action-items", includeDone],
    queryFn: () => api<{ items: ActionItem[] }>(`/api/console/v1/action-items?include_done=${includeDone}`),
    select: (d) => d.items,
  });
}

export function useCreateActionItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (text: string) =>
      api<{ id: number }>("/api/console/v1/action-items", { method: "POST", body: JSON.stringify({ text }) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't add that."),
    onSuccess: () => {
      toast.success("Added — it's in your Slack App Home too.");
      qc.invalidateQueries({ queryKey: ["action-items"] });
    },
  });
}

export function useCompleteActionItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api(`/api/console/v1/action-items/${id}/done`, { method: "POST" }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't mark that done."),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["action-items"] }),
  });
}

export function useSnoozeActionItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, remindAt }: { id: number; remindAt?: number }) =>
      api(`/api/console/v1/action-items/${id}/snooze`, {
        method: "POST", body: JSON.stringify({ remind_at: remindAt ?? null }),
      }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't snooze that."),
    onSuccess: () => { toast.success("Snoozed."); qc.invalidateQueries({ queryKey: ["action-items"] }); },
  });
}
