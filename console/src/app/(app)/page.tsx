"use client";

import Link from "next/link";
import { ApprovalRow } from "@/components/approvals/approval-row";
import { CodexStatusBanner } from "@/components/system/codex-status-banner";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { StatusPill } from "@/components/ui/status-pill";
import { Time } from "@/lib/time";
import { useApprovals, useDecide } from "@/lib/use-approvals";
import { useApprovalCount } from "@/lib/use-approval-count";
import { useJobCounts } from "@/lib/use-job-counts";
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

function SectionCard({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border bg-card shadow-sm">
      <div className="flex items-center border-b px-4 py-2.5 text-sm font-semibold">
        {title}
        {action && <div className="ml-auto">{action}</div>}
      </div>
      {children}
    </section>
  );
}

function AdminHome() {
  const queue = useApprovals("all");
  const counts = useApprovalCount();
  const jobs = useJobCounts();
  const decide = useDecide();
  const approvals = queue.data;

  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Tile label="Waiting for a decision" value={counts.data?.pending ?? "…"} hint="across everyone" href="/approvals" />
        <Tile label="Running now" value={jobs.data?.running ?? "…"} hint="jobs in progress" href="/activity" />
        <Tile label="Failed (24h)" value={jobs.data?.failed_24h ?? "…"} hint="need a look" href="/activity" />
      </div>

      <SectionCard title="Waiting for a decision">
        {queue.isLoading && <LoadingState rows={2} />}
        {queue.isError && <ErrorState onRetry={() => queue.refetch()} message="Couldn't load the approval queue." />}
        {!queue.isLoading && !queue.isError && !approvals?.length && (
          <EmptyState title="All clear" message="Nothing is waiting for a decision right now." />
        )}
        {approvals?.map((a) => (
          <ApprovalRow key={a.id} approval={a} onDecide={(id, approve) => decide.mutate({ id, approve })} />
        ))}
      </SectionCard>
    </>
  );
}

function MemberHome() {
  const mine = useApprovals("mine");
  const runs = useJobs("mine", 6);
  const decide = useDecide();
  const approvals = mine.data;
  const jobs = runs.data;

  return (
    <>
      <SectionCard title="Waiting for an admin">
        {mine.isLoading && <LoadingState rows={2} />}
        {mine.isError && <ErrorState onRetry={() => mine.refetch()} message="Couldn't load your requests." />}
        {!mine.isLoading && !mine.isError && !approvals?.length && (
          <EmptyState title="All clear" message="Bott isn't waiting on an admin for anything of yours." />
        )}
        {approvals?.map((a) => (
          <ApprovalRow key={a.id} approval={a} onDecide={(id, approve) => decide.mutate({ id, approve })} />
        ))}
      </SectionCard>

      <SectionCard
        title="Recent runs"
        action={<Link href="/activity" className="text-xs font-normal text-primary hover:underline">View all →</Link>}
      >
        {runs.isLoading && <LoadingState rows={2} />}
        {runs.isError && <ErrorState onRetry={() => runs.refetch()} message="Couldn't load your runs." />}
        {!runs.isLoading && !runs.isError && !jobs?.length && (
          <EmptyState title="No runs yet" message="No runs yet — ask Bott something in Slack." />
        )}
        <ul>
          {jobs?.map((j) => (
            <li key={j.id} className="flex items-center gap-2.5 border-b px-4 py-2.5 text-sm last:border-b-0">
              <StatusPill status={j.status} className="flex-none" />
              <span className="truncate">{j.kind}</span>
              <span className="ml-auto flex-none text-xs text-muted-foreground">
                <Time value={j.created} />
              </span>
            </li>
          ))}
        </ul>
      </SectionCard>
    </>
  );
}

export default function HomePage() {
  const { data: me } = useMe();
  const isAdmin = me?.is_admin ?? false;

  // Headline count is role-specific: admins see the org queue, members see their own.
  // Members never request scope=all (admin-only → 403); the shared query cache means
  // the role child re-using this scope costs no extra fetch.
  const headline = useApprovals(isAdmin ? "all" : "mine");
  const count = headline.data?.length ?? 0;

  const firstName = me?.email.split(".")[0] ?? "";
  const greeting = firstName ? firstName[0].toUpperCase() + firstName.slice(1) : "there";

  const subtitle = isAdmin
    ? count
      ? `${count} request${count > 1 ? "s" : ""} waiting for a decision`
      : "Nothing is waiting for a decision"
    : count
      ? `${count} request${count > 1 ? "s" : ""} waiting for an admin`
      : "Nothing of yours is waiting for an admin";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Hi, {greeting}</h1>
        <p className="text-sm text-muted-foreground">
          {subtitle}
          {!isAdmin && count ? " — Bott will act as soon as an admin approves." : ""}
        </p>
      </div>

      <CodexStatusBanner />

      {isAdmin ? <AdminHome /> : <MemberHome />}
    </div>
  );
}
