"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type PromptVersion = { id: number; prompt_name: string; content: string; note: string; author: string; created: number };
export type PromptState = { current: string; versions: PromptVersion[] };

export function usePrompt(name: string) {
  return useQuery({
    queryKey: ["prompt", name],
    queryFn: () => api<PromptState>(`/api/console/v1/prompts/${name}`),
  });
}

export function useSavePrompt(name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { content: string; note: string }) =>
      api<{ id: number }>(`/api/console/v1/prompts/${name}`, { method: "POST", body: JSON.stringify(body) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't save that version."),
    onSuccess: () => { toast.success("Saved a new version."); qc.invalidateQueries({ queryKey: ["prompt", name] }); },
  });
}

export function useRevertPrompt(name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: number) =>
      api<{ id: number }>(`/api/console/v1/prompts/${name}/revert/${versionId}`, { method: "POST" }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't revert."),
    onSuccess: () => { toast.success("Reverted."); qc.invalidateQueries({ queryKey: ["prompt", name] }); },
  });
}
