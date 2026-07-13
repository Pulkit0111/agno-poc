"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type Schedule = {
  id: string; label: string; kind: string; channel: string;
  cron: string; timezone: string; enabled: boolean; next_run: string;
  cadence: string; created_by: string | null; personal: boolean;
};

export function useSchedules() {
  return useQuery({
    queryKey: ["schedules"],
    queryFn: () => api<{ schedules: Schedule[] }>("/api/console/v1/schedules"),
    select: (d) => d.schedules,
  });
}

function useScheduleAction(path: (id: string) => string, method: "POST" | "DELETE" = "POST") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api(path(id), { method }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "That didn't work."),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
}

export function usePauseSchedule() { return useScheduleAction((id) => `/api/console/v1/schedules/${id}/pause`); }
export function useResumeSchedule() { return useScheduleAction((id) => `/api/console/v1/schedules/${id}/resume`); }
export function useRunScheduleNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api(`/api/console/v1/schedules/${id}/run-now`, { method: "POST" }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't start that run."),
    onSuccess: () => { toast.success("Running now."); qc.invalidateQueries({ queryKey: ["schedules"] }); },
  });
}
export function useDeleteSchedule() { return useScheduleAction((id) => `/api/console/v1/schedules/${id}`, "DELETE"); }

export type CreateScheduleInput = {
  kind: string; channel: string; time: string; frequency?: string;
  engagement?: string; account_name?: string; band?: string; team?: string;
};

export function useCreateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateScheduleInput) =>
      api<{ id: string }>("/api/console/v1/schedules", { method: "POST", body: JSON.stringify(body) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't create the schedule."),
    onSuccess: () => {
      toast.success("Schedule created — it'll also show up in Bott's App Home in Slack.");
      qc.invalidateQueries({ queryKey: ["schedules"] });
    },
  });
}

export type SchedulePreviewInput = { kind: string; frequency: string; time: string };
export type SchedulePreview = { next_run: string; cadence: string };

/** Live "what would this schedule look like" preview — no DB write. Used by the create
 * wizard's cadence step; safe to call repeatedly as the user adjusts frequency/time. */
export function useSchedulePreview() {
  return useMutation({
    mutationFn: (body: SchedulePreviewInput) =>
      api<SchedulePreview>("/api/console/v1/schedules/preview", { method: "POST", body: JSON.stringify(body) }),
  });
}
