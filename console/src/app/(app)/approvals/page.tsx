"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { ApprovalDrawer } from "@/components/approvals/approval-drawer";
import { ApprovalRow } from "@/components/approvals/approval-row";
import { EmptyState, ErrorState, LoadingState, NoAccessState } from "@/components/common/states";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { isForbidden } from "@/lib/api";
import { useApprovals, useDecide } from "@/lib/use-approvals";
import { useMe } from "@/lib/use-me";

function ApprovalsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { data: me } = useMe();
  const isAdmin = me?.is_admin ?? false;

  // Admins default to the org queue ("all") — deciding is the point. They can
  // switch to "Mine". Members only ever see their own requests.
  const wantsMine = params.get("scope") === "mine";
  const scope: "mine" | "all" = isAdmin ? (wantsMine ? "mine" : "all") : "mine";

  const rawId = params.get("id");
  const parsedId = rawId === null ? NaN : Number(rawId);
  const selected = Number.isFinite(parsedId) ? parsedId : null;
  const { data: approvals, isLoading, isError, error, refetch } = useApprovals(scope);
  const decide = useDecide();

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    router.replace(`/approvals?${next.toString()}`);
  };

  const subtitle = isAdmin
    ? scope === "all"
      ? "Everything Bott is holding for a decision"
      : "Your own requests to Bott"
    : "Requests waiting for an admin — Bott will act as soon as one approves";

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Approvals</h1>
          <p className="text-sm text-muted-foreground">{subtitle}</p>
        </div>
        {isAdmin && (
          <Tabs
            value={scope}
            onValueChange={(v) => setParam("scope", v === "mine" ? "mine" : null)}
            className="ml-auto"
          >
            <TabsList>
              <TabsTrigger value="all">All users</TabsTrigger>
              <TabsTrigger value="mine">Mine</TabsTrigger>
            </TabsList>
          </Tabs>
        )}
      </div>

      <div className="rounded-xl border bg-card shadow-sm">
        {isLoading && <LoadingState />}
        {isError && (isForbidden(error) ? <NoAccessState /> : <ErrorState onRetry={() => refetch()} />)}
        {!isLoading && !isError && !approvals?.length && (
          <EmptyState
            title={isAdmin ? "Nothing pending" : "All clear"}
            message={
              isAdmin
                ? "Approvals appear here the moment Bott needs a decision."
                : "Nothing of yours is waiting for an admin."
            }
          />
        )}
        {approvals?.map((a) => (
          <ApprovalRow
            key={a.id}
            approval={a}
            onDecide={(id, approve) => decide.mutate({ id, approve })}
            onOpen={(id) => setParam("id", String(id))}
          />
        ))}
      </div>

      <ApprovalDrawer
        id={selected}
        onClose={() => setParam("id", null)}
        onDecide={(id, approve) => decide.mutate({ id, approve })}
      />
    </div>
  );
}

export default function ApprovalsPage() {
  return (
    <Suspense>
      <ApprovalsInner />
    </Suspense>
  );
}
