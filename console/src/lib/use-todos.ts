"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export type Todo = { id: number; text: string; done: boolean; created: number };

export function useTodos() {
  return useQuery({
    queryKey: ["todos"],
    queryFn: () => api<{ items: Todo[] }>("/api/console/v1/todos"),
    select: (d) => d.items,
  });
}

export function useCreateTodo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (text: string) =>
      api<{ id: number }>("/api/console/v1/todos", { method: "POST", body: JSON.stringify({ text }) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't add that."),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["todos"] }),
  });
}

export function useToggleTodo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, done }: { id: number; done: boolean }) =>
      api(`/api/console/v1/todos/${id}/toggle`, { method: "POST", body: JSON.stringify({ done }) }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't update that."),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["todos"] }),
  });
}

export function useDeleteTodo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api(`/api/console/v1/todos/${id}`, { method: "DELETE" }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't delete that."),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["todos"] }),
  });
}

export function useClearDoneTodos() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ removed: number }>("/api/console/v1/todos/clear-done", { method: "POST" }),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Couldn't clear completed todos."),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["todos"] }),
  });
}
