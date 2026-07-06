"use client";

import Link from "next/link";
import { CircleCheck, CircleX, LoaderCircle } from "lucide-react";
import { ApprovalRow } from "@/components/approvals/approval-row";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/time";
import { useApprovals, useDecide } from "@/lib/use-approvals";
import { useJobs } from "@/lib/use-jobs";
import { useMe } from "@/lib/use-me";

function Tile({ label, value, hint, href }: { label: string; value: number | string; hint: string; href: string }) {
  return (
    <Link href={href} className="rounded-xl border bg-card p-4 shadow-sm hover:border-foreground/20">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>
    </Link>
  );
}

function JobIcon({ status }: { status: string }) {
  if (status === "done") return <CircleCheck className="size-3.5 text-green-600 dark:text-green-400" />;
  if (status === "error") return <CircleX className="size-3.5 text-red-600 dark:text-red-400" />;
  return <LoaderCircle className="size-3.5 animate-spin text-amber-600 dark:text-amber-400" />;
}

export default function HomePage() {
  const { data: me } = useMe();
  const { data: approvals, isLoading: loadingApprovals } = useApprovals("mine");
  const { data: jobs, isLoading: loadingJobs } = useJobs("mine", 6);
  const decide = useDecide();

  const firstName = me?.email.split(".")[0] ?? "";
  const greeting = firstName ? firstName[0].toUpperCase() + firstName.slice(1) : "there";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Hi, {greeting}</h1>
        <p className="text-sm text-muted-foreground">
          {approvals?.length
            ? `${approvals.length} thing${approvals.length > 1 ? "s are" : " is"} waiting on you`
            : "Nothing is waiting on you"}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Tile label="Waiting on you" value={approvals?.length ?? "…"} hint="approvals to decide" href="/approvals" />
        <Tile label="Recent runs" value={jobs?.length ?? "…"} hint="your latest activity" href="/activity" />
        <Tile label="Running now" value={jobs?.filter((j) => j.status === "running").length ?? "…"} hint="in progress" href="/activity" />
      </div>

      <section className="rounded-xl border bg-card shadow-sm">
        <div className="border-b px-4 py-2.5 text-sm font-semibold">Waiting on you</div>
        {loadingApprovals && <div className="space-y-2 p-4"><Skeleton className="h-10" /><Skeleton className="h-10" /></div>}
        {!loadingApprovals && !approvals?.length && (
          <div className="px-4 py-6 text-sm text-muted-foreground">
            All clear — Bott isn&apos;t holding anything for you.
          </div>
        )}
        {approvals?.map((a) => (
          <ApprovalRow key={a.id} approval={a} onDecide={(id, approve) => decide.mutate({ id, approve })} />
        ))}
      </section>

      <section className="rounded-xl border bg-card shadow-sm">
        <div className="flex items-center border-b px-4 py-2.5 text-sm font-semibold">
          Recent activity
          <Link href="/activity" className="ml-auto text-xs font-normal text-primary hover:underline">View all →</Link>
        </div>
        {loadingJobs && <div className="space-y-2 p-4"><Skeleton className="h-8" /><Skeleton className="h-8" /></div>}
        {!loadingJobs && !jobs?.length && (
          <div className="px-4 py-6 text-sm text-muted-foreground">No runs yet — ask Bott something in Slack.</div>
        )}
        <ul>
          {jobs?.map((j) => (
            <li key={j.id} className="flex items-center gap-2.5 border-b px-4 py-2 text-sm last:border-b-0">
              <JobIcon status={j.status} />
              <span className="truncate">{j.kind}</span>
              <span className="ml-auto flex-none text-xs text-muted-foreground">{relativeTime(j.created)}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
