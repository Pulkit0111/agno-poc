"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type PolicyOverride = { system: string; method: string; verdict: string; reason: string; updated_by: string; updated_at: number };

export function usePolicyOverrides() {
  return useQuery({
    queryKey: ["policy-overrides"],
    queryFn: () => api<{ overrides: PolicyOverride[] }>("/api/console/v1/policy/overrides"),
    select: (d) => d.overrides,
  });
}

export function useSetPolicyOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { system: string; method: string; verdict: string; reason: string }) =>
      api("/api/console/v1/policy/overrides", { method: "POST", body: JSON.stringify(body) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't set that override."),
    onSuccess: () => { toast.success("Override set."); qc.invalidateQueries({ queryKey: ["policy-overrides"] }); },
  });
}

export function useRemovePolicyOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ system, method }: { system: string; method: string }) =>
      api(`/api/console/v1/policy/overrides/${system}/${method}`, { method: "DELETE" }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't remove that override."),
    onSuccess: () => { toast.success("Override removed."); qc.invalidateQueries({ queryKey: ["policy-overrides"] }); },
  });
}

export function useClassify() {
  return useMutation({
    mutationFn: (body: { system: string; method: string }) =>
      api<{ verdict: string; reason: string }>("/api/console/v1/policy/classify", {
        method: "POST", body: JSON.stringify(body),
      }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't classify that."),
  });
}

export function useAllowedRepos() {
  return useQuery({
    queryKey: ["allowed-repos"],
    queryFn: () => api<{ repos: string[] }>("/api/console/v1/policy/repos"),
    select: (d) => d.repos,
  });
}
