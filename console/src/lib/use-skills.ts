"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type SkillRow = {
  name: string; description: string; instructions: string;
  built_in: boolean; pinned: boolean; authored_by: string | null;
};

export type SkillVersion = { id: number; slug: string; note: string; author: string; created: number };

export type SkillDetail = SkillRow & {
  content: string;
  versions: SkillVersion[];
};

/** The shape `POST /skills/draft` hands back — and exactly what `POST /skills` expects to save it. */
export type SkillDraft = { slug: string; name: string; description: string; content: string };

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: () => api<{ skills: SkillRow[] }>("/api/console/v1/skills"),
    select: (d) => d.skills,
  });
}

export function useSkill(slug: string) {
  return useQuery({
    queryKey: ["skill", slug],
    queryFn: () => api<SkillDetail>(`/api/console/v1/skills/${slug}`),
    enabled: !!slug,
  });
}

export function useUpdateSkill(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { content: string; note: string }) =>
      api<{ ok: boolean; version: number }>(`/api/console/v1/skills/${slug}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't save that version."),
    onSuccess: () => {
      // Deliberately no version number here: the PUT response's `version` is the
      // skill_versions autoincrement id shared across ALL skills, not a per-slug
      // counter — it would immediately diverge from the detail page's v{count}.
      toast.success("Saved — takes effect on Bott's next reload.");
      qc.invalidateQueries({ queryKey: ["skill", slug] });
      qc.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

/** One-shot draft: nothing is saved server-side. Used for both the initial draft and a
 * "Refine" re-draft (which just passes `feedback` alongside the same what/when). */
export function useDraftSkill() {
  return useMutation({
    mutationFn: (body: { what: string; when: string; feedback?: string }) =>
      api<SkillDraft>("/api/console/v1/skills/draft", { method: "POST", body: JSON.stringify(body) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't draft that skill — try again."),
  });
}

export function useSaveSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SkillDraft) =>
      api<{ slug: string }>("/api/console/v1/skills", { method: "POST", body: JSON.stringify(body) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't save that skill."),
    onSuccess: (_data, variables) => {
      toast.success(`Saved — ${variables.name} will be available after Bott's next reload.`);
      qc.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

export function usePinSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, pinned }: { name: string; pinned: boolean }) =>
      api(`/api/console/v1/skills/${name}/pin`, { method: "POST", body: JSON.stringify({ pinned }) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't update that skill."),
    onSuccess: (_data, { name, pinned }) => {
      toast.success(pinned ? "Pinned — protected from retirement" : "Unpinned — this skill can be retired");
      qc.invalidateQueries({ queryKey: ["skills"] });
      qc.invalidateQueries({ queryKey: ["skill", name] });
    },
  });
}

export function useRetireSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api(`/api/console/v1/skills/${name}/retire`, { method: "POST" }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't retire that skill."),
    onSuccess: (_data, name) => {
      toast.success("Retired — Bott will stop using this skill");
      qc.invalidateQueries({ queryKey: ["skills"] });
      qc.invalidateQueries({ queryKey: ["skill", name] });
    },
  });
}
