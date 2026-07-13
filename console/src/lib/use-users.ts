"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type Role = "admin" | "member";

export type ConsoleUser = {
  email: string;
  role: Role;
  /** Env-seeded (BOTT_ADMINS) — can't be demoted here, lockout protection. */
  locked: boolean;
  /** Invited but hasn't signed in yet — no last_active. */
  invited: boolean;
  last_active: number | null;
};

function serverMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function useUsers() {
  return useQuery({
    queryKey: ["users"],
    queryFn: () => api<{ users: ConsoleUser[] }>("/api/console/v1/users"),
    select: (d) => d.users,
  });
}

export function useSetRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ email, role }: { email: string; role: Role }) =>
      api(`/api/console/v1/users/${encodeURIComponent(email)}/role`, {
        method: "POST",
        body: JSON.stringify({ role }),
      }),
    onError: (err) => toast.error(serverMessage(err, "Couldn't change that role.")),
    onSuccess: (_data, { email, role }) => {
      toast.success(
        role === "admin"
          ? `${email} can now decide approvals and manage the platform`
          : `${email} is a member again`
      );
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
}

export function useInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; role: Role }) =>
      api("/api/console/v1/users/invite", { method: "POST", body: JSON.stringify(body) }),
    onError: (err) => toast.error(serverMessage(err, "Couldn't send that invite.")),
    onSuccess: () => {
      toast.success("Invited — they'll have access on first sign-in");
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
}

export function useRevokeInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (email: string) =>
      api(`/api/console/v1/users/invite/${encodeURIComponent(email)}`, { method: "DELETE" }),
    onError: (err) => toast.error(serverMessage(err, "Couldn't revoke that invite.")),
    onSuccess: () => {
      toast.success("Invite revoked");
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
}
