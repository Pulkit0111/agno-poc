"use client";

import { useState } from "react";
import { Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CategoryBadge } from "@/components/ui/category-badge";
import { StatusPill } from "@/components/ui/status-pill";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { ScheduleWizard } from "@/components/schedules/schedule-wizard";
import {
  useDeleteSchedule, useResumeSchedule, usePauseSchedule,
  useRunScheduleNow, useSchedules, type Schedule,
} from "@/lib/use-schedules";
import { useMe } from "@/lib/use-me";

function isMine(s: Schedule, viewerEmail: string | undefined): boolean {
  if (s.personal) return true;
  if (!viewerEmail || !s.created_by) return false;
  return s.created_by.toLowerCase() === viewerEmail.toLowerCase();
}

function ScheduleRow({ s, canManage }: { s: Schedule; canManage: boolean }) {
  const pause = usePauseSchedule();
  const resume = useResumeSchedule();
  const runNow = useRunScheduleNow();
  const del = useDeleteSchedule();

  return (
    <div className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <div className="truncate text-sm font-medium">{s.label}</div>
          {s.personal && <CategoryBadge kind="personal" />}
        </div>
        <div className="truncate text-xs text-muted-foreground">
          {s.cadence} → {s.channel || "DM"} · next run {s.next_run}
        </div>
      </div>
      <StatusPill tone={s.enabled ? "good" : "neutral"} label={s.enabled ? "Active" : "Paused"} />
      {canManage ? (
        <div className="flex flex-none gap-1.5">
          <Button size="sm" variant="outline" onClick={() => runNow.mutate(s.id)}>Run now</Button>
          {s.enabled
            ? <Button size="sm" variant="ghost" onClick={() => pause.mutate(s.id)}>Pause</Button>
            : <Button size="sm" variant="ghost" onClick={() => resume.mutate(s.id)}>Resume</Button>}
          <Button size="sm" variant="ghost" onClick={() => del.mutate(s.id)}>Remove</Button>
        </div>
      ) : (
        <span className="flex-none text-xs text-muted-foreground">managed by admins</span>
      )}
    </div>
  );
}

export default function SchedulesPage() {
  const { data: me } = useMe();
  const { data: schedules, isLoading, isError, refetch } = useSchedules();
  const [wizardOpen, setWizardOpen] = useState(false);
  // Bumped on every open so ScheduleWizard remounts fresh instead of resetting its own
  // state in an effect (avoids the cascading-render anti-pattern for reset-on-reopen).
  const [wizardKey, setWizardKey] = useState(0);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-lg tracking-tight">Schedules</h1>
          <p className="text-sm text-muted-foreground">Recurring work Bott does on its own and posts to Slack</p>
        </div>
        <Button onClick={() => { setWizardKey((k) => k + 1); setWizardOpen(true); }}>New schedule</Button>
      </div>

      <div className="flex gap-2 rounded-xl border bg-muted/40 px-3 py-2.5 text-sm">
        <Info className="mt-0.5 size-4 flex-none text-muted-foreground" />
        <p className="text-muted-foreground">
          <b className="font-medium text-foreground">These are live.</b> Every schedule fires for real and posts
          its result to the Slack channel shown — it&apos;s the same list you see in Bott&apos;s App Home in Slack.
        </p>
      </div>

      <div className="rounded-xl border bg-card shadow-sm">
        {isLoading && <LoadingState />}
        {isError && <ErrorState message="Couldn't load — try refreshing the page." onRetry={() => refetch()} />}
        {!isLoading && !isError && !schedules?.length && (
          <EmptyState title="No schedules yet" message="Create one to have Bott do recurring work on its own." />
        )}
        {schedules?.map((s) => (
          <ScheduleRow key={s.id} s={s} canManage={!!me?.is_admin || isMine(s, me?.email)} />
        ))}
      </div>

      {!me?.is_admin && (
        <p className="text-xs text-muted-foreground">
          You manage your own schedules here; team digests are managed by admins.
        </p>
      )}

      <ScheduleWizard key={wizardKey} open={wizardOpen} onOpenChange={setWizardOpen} />
    </div>
  );
}
