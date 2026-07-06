"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type ConnectorStatus = { name: string; ok: boolean; on: string; off: string };

export function useConnectors() {
  return useQuery({
    queryKey: ["connectors"],
    queryFn: () => api<{ connectors: ConnectorStatus[] }>("/api/console/v1/connectors"),
    select: (d) => d.connectors,
  });
}
