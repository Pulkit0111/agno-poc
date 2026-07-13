"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type ProviderInfo = { name: string; usable: boolean; hint: string | null; models: string[] };
export type CodexUsage = {
  window_s: number; requests: number; output_tokens: number;
  top_users: { user_id: string; requests: number }[];
};

/** The three model roles, wherever they land in the payload. */
export type ActiveModels = { provider: string; chat: string; build: string; review: string };

/** Admin payload: flat active-model fields plus conflict/usage detail. */
export type AdminModelsState = ActiveModels & {
  conflict: boolean;
  swap_preview: string | null;
  providers: ProviderInfo[];
  codex_usage: CodexUsage | null;
};

/** Member payload (Task 2): trimmed down to just what's active, nested under `active`. */
export type MemberModelsState = {
  active: ActiveModels;
  providers: ProviderInfo[];
};

export type ModelsState = AdminModelsState | MemberModelsState;

/** True for the admin shape (flat fields, no `active` wrapper). */
export function isAdminModels(data: ModelsState): data is AdminModelsState {
  return !("active" in data);
}

/** Unified read of the active chat/build/review models regardless of caller role. */
export function getActiveModels(data: ModelsState): ActiveModels {
  return isAdminModels(data) ? data : data.active;
}

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
