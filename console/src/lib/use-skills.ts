"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type SkillRow = {
  name: string; description: string; instructions: string;
  built_in: boolean; pinned: boolean; authored_by: string | null;
};

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: () => api<{ skills: SkillRow[] }>("/api/console/v1/skills"),
    select: (d) => d.skills,
  });
}

export function usePinSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, pinned }: { name: string; pinned: boolean }) =>
      api(`/api/console/v1/skills/${name}/pin`, { method: "POST", body: JSON.stringify({ pinned }) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't update that skill."),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills"] }),
  });
}

export function useRetireSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api(`/api/console/v1/skills/${name}/retire`, { method: "POST" }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't retire that skill."),
    onSuccess: () => { toast.success("Retired."); qc.invalidateQueries({ queryKey: ["skills"] }); },
  });
}
