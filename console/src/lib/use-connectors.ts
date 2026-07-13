"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type ConnectorStatus = {
  name: string;
  ok: boolean;
  on: string;
  off: string;
  /** Numbered, plain-language steps to fix a broken/unconfigured connector. */
  fix?: string[];
};

export type ConnectorTestResult = { ok: boolean; message: string };

export type ConnectorType = "github_app" | "sentry_org" | "http_api";

export type AddConnectorBody = { type: ConnectorType; fields: Record<string, string> };

function serverMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function useConnectors() {
  return useQuery({
    queryKey: ["connectors"],
    queryFn: () => api<{ connectors: ConnectorStatus[] }>("/api/console/v1/connectors"),
    select: (d) => d.connectors,
  });
}

/** Live round-trip test for one connector (admin-only). Cheap enough to run on a
 * connected connector too, as a quick "is this suspiciously broken?" check. */
export function useTestConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api<ConnectorTestResult>(`/api/console/v1/connectors/${encodeURIComponent(name.toLowerCase())}/test`, {
        method: "POST",
      }),
    onError: (err) => toast.error(serverMessage(err, "Couldn't test that connector.")),
    onSuccess: (result) => {
      if (result.ok) toast.success(result.message || "Connected.");
      else toast.error(result.message || "That connector isn't reachable right now.");
      qc.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
}

/** Add-connector drawer (admin-only) — probes the candidate credentials server-side
 * BEFORE storing anything; a 422 (probe failure or bad fields) surfaces as `error` on
 * the mutation for inline display, deliberately with no toast (the drawer shows it). */
export function useAddConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AddConnectorBody) =>
      api<{ ok: boolean; name: string }>("/api/console/v1/connectors/add", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (result, variables) => {
      toast.success(`Connected — ${connectorLabel(variables.type)} is live`);
      qc.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
}

/** Remove a store-backed (console-added) connector. */
export function useRemoveConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api(`/api/console/v1/connectors/${encodeURIComponent(name)}`, { method: "DELETE" }),
    onError: (err) => toast.error(serverMessage(err, "Couldn't remove that connector.")),
    onSuccess: () => {
      toast.success("Connector removed.");
      qc.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
}

export function connectorLabel(type: ConnectorType): string {
  return {
    github_app: "GitHub (org app)",
    sentry_org: "Sentry (second org)",
    http_api: "the custom HTTP API",
  }[type];
}
