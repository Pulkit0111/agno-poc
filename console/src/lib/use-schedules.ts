"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type Schedule = {
  id: string; label: string; kind: string; channel: string;
  cron: string; timezone: string; enabled: boolean; next_run: string;
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
  const base = useScheduleAction((id) => `/api/console/v1/schedules/${id}/run-now`);
  return { ...base, mutate: (id: string) => { base.mutate(id); toast.success("Running now."); } };
}
export function useDeleteSchedule() { return useScheduleAction((id) => `/api/console/v1/schedules/${id}`, "DELETE"); }

export type CreateScheduleInput = {
  kind: string; channel: string; time: string; frequency?: string;
  engagement?: string; account_name?: string; band?: string;
};

export function useCreateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateScheduleInput) =>
      api<{ id: string }>("/api/console/v1/schedules", { method: "POST", body: JSON.stringify(body) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't create the schedule."),
    onSuccess: () => { toast.success("Schedule created."); qc.invalidateQueries({ queryKey: ["schedules"] }); },
  });
}
