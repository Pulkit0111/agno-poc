"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type Engagement = { channel_id: string; engagement: string; schedule_count: number };

export function useEngagements() {
  return useQuery({
    queryKey: ["engagements"],
    queryFn: () => api<{ engagements: Engagement[] }>("/api/console/v1/engagements"),
    select: (d) => d.engagements,
  });
}

export function useMapEngagement() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { channel_id: string; engagement: string }) =>
      api("/api/console/v1/engagements", { method: "POST", body: JSON.stringify(body) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't map that channel."),
    onSuccess: () => { toast.success("Mapped."); qc.invalidateQueries({ queryKey: ["engagements"] }); },
  });
}

export function useUnmapEngagement() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (channelId: string) => api(`/api/console/v1/engagements/${channelId}`, { method: "DELETE" }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't unmap that channel."),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["engagements"] }),
  });
}
