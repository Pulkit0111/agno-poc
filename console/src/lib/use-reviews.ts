"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type Review = {
  pr: string;
  verdict: string;
  url: string | null;
  created: number;
};

/** Admin-only feed of past PR reviews (verdict + link). */
export function useReviews() {
  return useQuery({
    queryKey: ["reviews"],
    queryFn: () => api<{ reviews: Review[] }>("/api/console/v1/reviews"),
    select: (d) => d.reviews,
    refetchInterval: 30_000,
  });
}
