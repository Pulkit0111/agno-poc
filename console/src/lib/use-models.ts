"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type ProviderInfo = { name: string; usable: boolean; hint: string; models: string[] };
export type CodexUsage = {
  window_s: number; requests: number; output_tokens: number;
  top_users: { user_id: string; requests: number }[];
};
export type ModelsState = {
  provider: string; chat: string; build: string; review: string;
  conflict: boolean; swap_preview: string | null; providers: ProviderInfo[];
  codex_usage: CodexUsage | null;
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
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (authJson: string) =>
      api<{ message: string }>("/api/console/v1/models/connect-codex", {
        method: "POST", body: JSON.stringify({ auth_json: authJson }),
      }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't connect Codex."),
    onSuccess: (data) => { toast.success(data.message); qc.invalidateQueries({ queryKey: ["models"] }); },
  });
}

export type CodexLoginStart = { url?: string; code?: string; raw?: string };

export function useStartCodexLogin() {
  return useMutation({
    mutationFn: () => api<CodexLoginStart>("/api/console/v1/models/codex-login/start", { method: "POST" }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't start login."),
  });
}

export function useCodexLoginStatus(enabled: boolean) {
  return useQuery({
    queryKey: ["codex-login-status"],
    queryFn: () => api<{ connected: boolean }>("/api/console/v1/models/codex-login/status"),
    enabled,
    refetchInterval: enabled ? 3000 : false,
  });
}

export function useDisconnectCodex() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ connected: boolean }>("/api/console/v1/models/codex-login/disconnect", { method: "POST" }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't disconnect."),
    onSuccess: () => {
      toast.success("Disconnected.");
      qc.invalidateQueries({ queryKey: ["models"] });
      qc.invalidateQueries({ queryKey: ["codex-login-status"] });
    },
  });
}
