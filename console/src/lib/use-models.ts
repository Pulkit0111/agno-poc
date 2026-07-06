"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type ProviderInfo = { name: string; usable: boolean; hint: string; models: string[] };
export type ModelsState = {
  provider: string; chat: string; build: string; review: string;
  conflict: boolean; swap_preview: string | null; providers: ProviderInfo[];
};

export function useModels() {
  return useQuery({
    queryKey: ["models"],
    queryFn: () => api<ModelsState>("/api/console/v1/models"),
  });
}

export function useSetModelOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { key: string; value: string }) =>
      api<{ message: string }>("/api/console/v1/models", { method: "POST", body: JSON.stringify(body) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't update that model."),
    onSuccess: (data) => { toast.success(data.message); qc.invalidateQueries({ queryKey: ["models"] }); },
  });
}

export function useConnectCodex() {
  return useMutation({
    mutationFn: (authJson: string) =>
      api<{ message: string }>("/api/console/v1/models/connect-codex", {
        method: "POST", body: JSON.stringify({ auth_json: authJson }),
      }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't connect Codex."),
    onSuccess: (data) => toast.success(data.message),
  });
}
