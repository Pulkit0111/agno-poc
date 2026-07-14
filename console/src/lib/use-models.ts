"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type ProviderInfo = { name: string; usable: boolean; hint: string | null; models: string[] };
export type CodexUsage = {
  window_s: number; requests: number; output_tokens: number;
  top_users: { user_id: string; requests: number }[];
};

/** Valid `model.provider.<role>` values (Task 3, Part A) — kept in sync with the
 * backend's `_VALID_PROVIDERS` in bott.interfaces.slack_home.models. */
export type ProviderName = "codex" | "openrouter" | "bedrock";

/** The three model roles, wherever they land in the payload. */
export type ActiveModels = { provider: string; chat: string; build: string; review: string };

/** Which provider each role currently resolves to — chat/build/review may each sit on a
 * different provider via `model.provider.<role>`. */
export type ProvidersByRole = { chat: ProviderName; build: ProviderName; review: ProviderName };

/** The full task→model matrix, as nested under `active` in both the admin and member
 * payloads (the backend computes it once, before branching on role). */
export type FullActive = ActiveModels & { providers_by_role: ProvidersByRole };

/** Per-provider model-id catalogs, admin-only — feeds the per-role model dropdown once a
 * provider is picked. */
export type Catalogs = { codex: string[]; openrouter: string[]; bedrock: string[] };

/** Admin payload: flat active-model fields plus conflict/usage detail, plus the additive
 * `active`/`catalogs` the per-role provider picker needs. */
export type AdminModelsState = ActiveModels & {
  conflict: boolean;
  swap_preview: string | null;
  providers: ProviderInfo[];
  codex_usage: CodexUsage | null;
  active: FullActive;
  catalogs: Catalogs;
};

/** Member payload (Task 2): trimmed down to just what's active, nested under `active`. */
export type MemberModelsState = {
  active: FullActive;
  providers: ProviderInfo[];
};

export type ModelsState = AdminModelsState | MemberModelsState;

/** True for the admin shape. Both shapes now carry `active` (Task 3 made it additive to
 * the admin payload too), so the discriminator can't be "no `active` wrapper" any more —
 * `catalogs` is admin-only (the backend omits it entirely for members; see
 * test_member_get_has_no_catalogs_key), so key on that instead. */
export function isAdminModels(data: ModelsState): data is AdminModelsState {
  return "catalogs" in data;
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
