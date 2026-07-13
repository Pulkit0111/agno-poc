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
