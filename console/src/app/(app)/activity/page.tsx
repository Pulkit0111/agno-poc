"use client";

import { useState } from "react";
import { JobDrawer } from "@/components/jobs/job-drawer";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { StatusPill } from "@/components/ui/status-pill";
import { Time } from "@/lib/time";
import type { Job } from "@/lib/types";
import { useJobs } from "@/lib/use-jobs";
import { useJobCounts } from "@/lib/use-job-counts";
import { useMe } from "@/lib/use-me";

/** Map a raw job kind to a human label. Covers the known kinds; falls back to a title-case. */
const KIND_LABELS: Record<string, string> = {
  plan: "Build & Fix",
  implement: "Build & Fix",
  "build.implement": "Build & Fix",
  review: "PR review",
  rereview: "PR re-review",
  triage: "Sentry triage",
  sprint: "Sprint report",
  sprint_snapshot: "Sprint snapshot",
  delivery: "Delivery report",
  security: "Security check",
  portfolio: "Portfolio snapshot",
};

function humanizeKind(kind: string): string {
  if (KIND_LABELS[kind]) return KIND_LABELS[kind];
  return kind
    .replace(/[._]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function elapsed(sinceEpochSeconds: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - sinceEpochSeconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

function Tile({ label, value, tone }: { label: string; value: number | string; tone?: "bad" }) {
  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tracking-tight ${tone === "bad" && value ? "text-red-700 dark:text-red-400" : ""}`}>
        {value}
      </div>
    </div>
  );
}

/** Admin-only stat tiles. Kept as its own component so the underlying `useJobCounts` query
 *  (admin-only, would 403-loop for members) never mounts unless the caller is an admin —
 *  same pattern as the sidebar's ApprovalBadge. */
function StatTiles() {
  const counts = useJobCounts();
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <Tile label="Running now" value={counts.data?.running ?? 0} />
      <Tile label="Done" value={counts.data?.done ?? 0} />
      <Tile label="Failed (24h)" value={counts.data?.failed_24h ?? 0} tone="bad" />
    </div>
  );
}

function LiveDot() {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
      <span className="relative flex size-2">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-green-500 opacity-60" />
        <span className="relative inline-flex size-2 rounded-full bg-green-500" />
      </span>
      Live
    </span>
  );
}

export default function ActivityPage() {
  const { data: me, isLoading: meLoading } = useMe();
  const isAdmin = me?.is_admin ?? false;
  const [scope, setScope] = useState<"mine" | "all">("all");
  const [selected, setSelected] = useState<number | null>(null);
  // Members only ever see their own runs — the "all" scope is admin-only server-side.
  const effectiveScope = isAdmin ? scope : "mine";
  const activity = useJobs(effectiveScope, 50);

  if (meLoading) return <LoadingState rows={5} />;

  const jobs = activity.data;

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-4">
        <div>
          <h1 className="font-display text-lg tracking-tight">Activity</h1>
          <p className="text-sm text-muted-foreground">
            Every run — builds, reviews, reports, scheduled digests. Click a run for the full story.
          </p>
        </div>
        <div className="ml-auto pt-1">
          <LiveDot />
        </div>
      </div>

      {isAdmin && <StatTiles />}

      {isAdmin && (
        <div className="flex gap-1 border-b text-sm">
          <button
            type="button"
            onClick={() => setScope("all")}
            className={`border-b-2 px-3 py-1.5 ${scope === "all" ? "border-primary font-medium text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          >
            Everyone
          </button>
          <button
            type="button"
            onClick={() => setScope("mine")}
            className={`border-b-2 px-3 py-1.5 ${scope === "mine" ? "border-primary font-medium text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          >
            Mine
          </button>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
        {activity.isLoading ? (
          <LoadingState rows={6} />
        ) : activity.isError ? (
          <ErrorState message="Couldn't load the activity feed." onRetry={() => activity.refetch()} />
        ) : !jobs?.length ? (
          <EmptyState title="Nothing running" message="Bott isn't working on anything right now." />
        ) : (
          <ul>
            {jobs.map((j: Job) => (
              <li key={j.id}>
                <button
                  onClick={() => setSelected(j.id)}
                  className="flex w-full items-center gap-3 border-b px-4 py-3 text-left last:border-b-0 hover:bg-muted/50"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{humanizeKind(j.kind)}</div>
                    {isAdmin && j.user_id && (
                      <div className="truncate text-xs text-muted-foreground">asked by {j.user_id}</div>
                    )}
                  </div>
                  <StatusPill status={j.status} />
                  <div className="w-24 flex-none text-right text-xs text-muted-foreground">
                    {j.status === "running" ? (
                      <span title="running for">{elapsed(j.created)}</span>
                    ) : (
                      <Time value={j.created} />
                    )}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <JobDrawer id={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
