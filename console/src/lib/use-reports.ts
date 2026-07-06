"use client";

import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type ReportRunInput = {
  kind: string; engagement?: string; channel?: string; team?: string;
};

export function useRunReport() {
  return useMutation({
    mutationFn: (body: ReportRunInput) =>
      api<{ result: string }>("/api/console/v1/reports/run", { method: "POST", body: JSON.stringify(body) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "That report couldn't run."),
  });
}
