"use client";

import Link from "next/link";
import { ApprovalRow } from "@/components/approvals/approval-row";
import { ModelCard } from "@/components/home/model-card";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-pill";
import { Time } from "@/lib/time";
import { useApprovals, useDecide } from "@/lib/use-approvals";
import { useApprovalCount } from "@/lib/use-approval-count";
import { useJobCounts } from "@/lib/use-job-counts";
import { useJobs } from "@/lib/use-jobs";
import { useActionItems, useCompleteActionItem } from "@/lib/use-action-items";
import { useSchedules } from "@/lib/use-schedules";
import { useMe } from "@/lib/use-me";

function StatTile({
  label, value, hint, onClick, href,
}: { label: string; value: number | string; hint: string; onClick?: () => void; href?: string }) {
  const inner = (
    <>
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="font-display mt-1 text-2xl tabular-nums tracking-tight">{value}</div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>
    </>
  );
  const className = "block rounded-xl border bg-card p-4 text-left shadow-sm hover:border-foreground/20";
  if (href) return <Link href={href} className={className}>{inner}</Link>;
  return <button type="button" onClick={onClick} className={className}>{inner}</button>;
}

function SectionCard({
  title, action, hint, children,
}: { title: string; action?: React.ReactNode; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border bg-card shadow-sm">
      <div className="flex items-center gap-2 border-b px-4 py-2.5 text-sm font-semibold">
        {title}
        {hint && <span className="ml-2 text-xs font-normal text-muted-foreground">{hint}</span>}
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
  const activity = useJobs("all", 6);
  const decide = useDecide();
  const approvals = queue.data;
  const runs = activity.data;

  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile
          label="Need a decision"
          value={counts.data?.pending ?? "…"}
          hint="across everyone"
          onClick={() => document.getElementById("decision-card")?.scrollIntoView({ behavior: "smooth" })}
        />
        <StatTile label="Running now" value={jobs.data?.running ?? "…"} hint="jobs in progress" href="/activity" />
        <StatTile label="Failed (24h)" value={jobs.data?.failed_24h ?? "…"} hint="need a look" href="/activity" />
      </div>

      <div id="decision-card">
        <SectionCard title="Needs a decision" hint="also actionable from the Slack thread">
          {queue.isLoading && <LoadingState rows={2} />}
          {queue.isError && <ErrorState onRetry={() => queue.refetch()} message="Couldn't load the approval queue." />}
          {!queue.isLoading && !queue.isError && !approvals?.length && (
            <EmptyState title="All clear" message="Nothing is waiting for a decision right now." />
          )}
          {approvals?.map((a) => (
            <ApprovalRow key={a.id} approval={a} onDecide={(id, approve) => decide.mutate({ id, approve })} />
          ))}
        </SectionCard>
      </div>

      <SectionCard
        title="Recent activity — everyone"
        action={<Link href="/activity" className="text-xs font-normal text-primary hover:underline">View all →</Link>}
      >
        {activity.isLoading && <LoadingState rows={3} />}
        {activity.isError && <ErrorState onRetry={() => activity.refetch()} message="Couldn't load recent activity." />}
        {!activity.isLoading && !activity.isError && !runs?.length && (
          <EmptyState title="Nothing yet" message="Bott hasn't run anything yet." />
        )}
        <ul>
          {runs?.map((j) => (
            <li key={j.id} className="flex items-center gap-2.5 border-b px-4 py-2.5 text-sm last:border-b-0">
              <StatusPill status={j.status} className="flex-none" />
              <span className="min-w-0 flex-1 truncate">{j.kind}</span>
              {j.user_id && <span className="flex-none text-xs text-muted-foreground">{j.user_id}</span>}
              <span className="flex-none text-xs text-muted-foreground">
                <Time value={j.created} />
              </span>
            </li>
          ))}
        </ul>
      </SectionCard>
    </>
  );
}

function MemberHome() {
  const mine = useApprovals("mine");
  const items = useActionItems(false);
  const complete = useCompleteActionItem();
  const runs = useJobs("mine", 6);
  const schedules = useSchedules();
  const decide = useDecide();
  const approvals = mine.data;
  const jobs = runs.data;
  const actionItems = items.data?.slice(0, 3);
  const mySchedules = schedules.data?.slice(0, 3);

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2">
        <SectionCard title="Waiting on an admin">
          {mine.isLoading && <LoadingState rows={2} />}
          {mine.isError && <ErrorState onRetry={() => mine.refetch()} message="Couldn't load your requests." />}
          {!mine.isLoading && !mine.isError && !approvals?.length && (
            <EmptyState title="All clear" message="Bott isn't waiting on an admin for anything of yours." />
          )}
          {approvals?.map((a) => (
            <ApprovalRow key={a.id} approval={a} onDecide={(id, approve) => decide.mutate({ id, approve })} />
          ))}
          {!!approvals?.length && (
            <p className="px-4 pb-3 text-[11.5px] text-muted-foreground">
              Bott will act the moment an admin approves — you&apos;ll get the result in your Slack thread.
            </p>
          )}
        </SectionCard>

        <SectionCard
          title="Your action items"
          action={<Link href="/action-items" className="text-xs font-normal text-primary hover:underline">All →</Link>}
        >
          {items.isLoading && <LoadingState rows={2} />}
          {items.isError && <ErrorState onRetry={() => items.refetch()} message="Couldn't load your action items." />}
          {!items.isLoading && !items.isError && !actionItems?.length && (
            <EmptyState title="Nothing open" message="You're all caught up." />
          )}
          {actionItems?.map((item) => (
            <div key={item.id} className="flex items-center gap-3 border-b px-4 py-2.5 last:border-b-0">
              <span className="min-w-0 flex-1 truncate text-sm">{item.text}</span>
              <Button size="sm" variant="outline"
                className="flex-none border-green-600/30 text-green-700 hover:bg-green-600/10 dark:text-green-400"
                onClick={() => complete.mutate(item.id)}>
                Done
              </Button>
            </div>
          ))}
        </SectionCard>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <SectionCard
          title="Your recent runs"
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

        <SectionCard
          title="Your schedules"
          action={<Link href="/schedules" className="text-xs font-normal text-primary hover:underline">Manage →</Link>}
        >
          {schedules.isLoading && <LoadingState rows={2} />}
          {schedules.isError && <ErrorState onRetry={() => schedules.refetch()} message="Couldn't load your schedules." />}
          {!schedules.isLoading && !schedules.isError && !mySchedules?.length && (
            <EmptyState title="No schedules yet" message="Nothing recurring is set up for you yet." />
          )}
          {mySchedules?.map((s) => (
            <div key={s.id} className="flex items-center gap-3 border-b px-4 py-2.5 last:border-b-0">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{s.label}</div>
                <div className="text-xs text-muted-foreground">{s.channel} · {s.next_run}</div>
              </div>
              <StatusPill tone={s.enabled ? "good" : "neutral"} label={s.enabled ? "Active" : "Paused"} className="flex-none" />
            </div>
          ))}
        </SectionCard>
      </div>
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
        <h1 className="font-display text-lg tracking-tight">Hi, {greeting}</h1>
        <p className="text-sm text-muted-foreground">
          {subtitle}
          {!isAdmin && count ? " — Bott will act as soon as an admin approves." : ""}
        </p>
      </div>

      <ModelCard />

      {isAdmin ? <AdminHome /> : <MemberHome />}
    </div>
  );
}
