"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { ApprovalDrawer } from "@/components/approvals/approval-drawer";
import { ApprovalRow } from "@/components/approvals/approval-row";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApprovals, useDecide } from "@/lib/use-approvals";
import { useMe } from "@/lib/use-me";

function ApprovalsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { data: me } = useMe();
  const scope = (params.get("scope") === "all" && me?.is_admin ? "all" : "mine") as "mine" | "all";
  const rawId = params.get("id");
  const parsedId = rawId === null ? NaN : Number(rawId);
  const selected = Number.isFinite(parsedId) ? parsedId : null;
  const { data: approvals, isLoading } = useApprovals(scope);
  const decide = useDecide();

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    router.replace(`/approvals?${next.toString()}`);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Approvals</h1>
          <p className="text-sm text-muted-foreground">Everything Bott is holding for a human decision</p>
        </div>
        {me?.is_admin && (
          <Tabs value={scope} onValueChange={(v) => setParam("scope", v === "mine" ? null : v)} className="ml-auto">
            <TabsList>
              <TabsTrigger value="mine">Mine</TabsTrigger>
              <TabsTrigger value="all">All users</TabsTrigger>
            </TabsList>
          </Tabs>
        )}
      </div>

      <div className="rounded-xl border bg-card shadow-sm">
        {isLoading && <div className="space-y-2 p-4"><Skeleton className="h-10" /><Skeleton className="h-10" /></div>}
        {!isLoading && !approvals?.length && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">
            Nothing pending. Approvals appear here the moment Bott needs a decision.
          </div>
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
