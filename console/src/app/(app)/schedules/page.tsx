"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCreateSchedule, usePauseSchedule, useResumeSchedule,
  useRunScheduleNow, useDeleteSchedule, useSchedules,
} from "@/lib/use-schedules";
import { useMe } from "@/lib/use-me";

const KINDS = [
  { value: "security", label: "Security digest" },
  { value: "portfolio", label: "Portfolio dashboard" },
  { value: "sentiment", label: "Sentiment report" },
  { value: "delivery", label: "Delivery digest" },
  { value: "sprint", label: "Sprint report" },
];
const FREQUENCIES = [
  { value: "daily", label: "Every day" },
  { value: "weekdays", label: "Every weekday (Mon–Fri)" },
  { value: "weekly", label: "Every Monday" },
];

export default function SchedulesPage() {
  const { data: me } = useMe();
  const { data: schedules, isLoading, isError } = useSchedules();
  const pause = usePauseSchedule();
  const resume = useResumeSchedule();
  const runNow = useRunScheduleNow();
  const del = useDeleteSchedule();
  const create = useCreateSchedule();

  const [kind, setKind] = useState("security");
  const [channel, setChannel] = useState("");
  const [time, setTime] = useState("09:00");
  const [frequency, setFrequency] = useState("daily");
  const [engagement, setEngagement] = useState("");
  const [accountName, setAccountName] = useState("");
  const [band, setBand] = useState("");

  const needsEngagement = kind === "sprint" || kind === "delivery";
  const needsFrequency = kind !== "sprint";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Schedules</h1>
        <p className="text-sm text-muted-foreground">Recurring work Bott does without being asked</p>
      </div>

      <div className="rounded-xl border bg-card shadow-sm">
        {isLoading && <div className="space-y-2 p-4"><Skeleton className="h-9" /><Skeleton className="h-9" /></div>}
        {isError && (
          <div className="px-4 py-8 text-center text-sm text-destructive">
            Couldn&apos;t load — try refreshing the page.
          </div>
        )}
        {!isLoading && !isError && !schedules?.length && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            No schedules yet — create one below.
          </div>
        )}
        {schedules?.map((s) => (
          <div key={s.id} className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{s.label}</div>
              <div className="text-xs text-muted-foreground">{s.channel} · {s.next_run}</div>
            </div>
            <Badge variant="outline" className={s.enabled ? "text-green-700 dark:text-green-400" : "text-muted-foreground"}>
              {s.enabled ? "Active" : "Paused"}
            </Badge>
            {me?.is_admin && (
              <div className="flex flex-none gap-1.5">
                <Button size="sm" variant="outline" onClick={() => runNow.mutate(s.id)}>Run now</Button>
                {s.enabled
                  ? <Button size="sm" variant="ghost" onClick={() => pause.mutate(s.id)}>Pause</Button>
                  : <Button size="sm" variant="ghost" onClick={() => resume.mutate(s.id)}>Resume</Button>}
                <Button size="sm" variant="ghost" onClick={() => del.mutate(s.id)}>Remove</Button>
              </div>
            )}
          </div>
        ))}
      </div>

      {!me?.is_admin && (
        <p className="text-sm text-muted-foreground">
          Creating, pausing, or removing schedules needs an admin — ask one to make changes here.
        </p>
      )}

      {me?.is_admin && (
      <div className="max-w-lg rounded-xl border bg-card shadow-sm">
        <div className="border-b px-4 py-2.5 text-sm font-semibold">New schedule</div>
        <div className="space-y-3 p-4">
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-muted-foreground">What</span>
            <select className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" value={kind} onChange={(e) => setKind(e.target.value)}>
              {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
          </label>
          {needsEngagement && (
            <label className="block text-sm">
              <span className="mb-1 block text-xs font-medium text-muted-foreground">Engagement</span>
              <input className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" value={engagement} onChange={(e) => setEngagement(e.target.value)} placeholder="acme-commerce" />
            </label>
          )}
          {kind === "delivery" && (
            <>
              <label className="block text-sm">
                <span className="mb-1 block text-xs font-medium text-muted-foreground">Account name (optional)</span>
                <input className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" value={accountName} onChange={(e) => setAccountName(e.target.value)} />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-xs font-medium text-muted-foreground">Band (optional)</span>
                <input className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" value={band} onChange={(e) => setBand(e.target.value)} />
              </label>
            </>
          )}
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-muted-foreground">Channel</span>
            <input className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" value={channel} onChange={(e) => setChannel(e.target.value)} placeholder="#proj-acme" />
          </label>
          {needsFrequency && (
            <label className="block text-sm">
              <span className="mb-1 block text-xs font-medium text-muted-foreground">Cadence</span>
              <select className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
                {FREQUENCIES.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
              </select>
            </label>
          )}
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-muted-foreground">Time</span>
            <input type="time" className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" value={time} onChange={(e) => setTime(e.target.value)} />
          </label>
          <Button
            className="w-full"
            disabled={create.isPending || !channel || (needsEngagement && !engagement)}
            onClick={() => create.mutate({
              kind, channel, time,
              frequency: needsFrequency ? frequency : undefined,
              engagement: needsEngagement ? engagement : undefined,
              account_name: kind === "delivery" ? (accountName || undefined) : undefined,
              band: kind === "delivery" ? (band || undefined) : undefined,
            })}
          >
            Create schedule
          </Button>
        </div>
      </div>
      )}
    </div>
  );
}
