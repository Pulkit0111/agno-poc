"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type KnownUser = { user_id: string; last_active: number; is_admin: boolean };

export function useUsers() {
  return useQuery({
    queryKey: ["users"],
    queryFn: () => api<{ users: KnownUser[] }>("/api/console/v1/users"),
    select: (d) => d.users,
  });
}
