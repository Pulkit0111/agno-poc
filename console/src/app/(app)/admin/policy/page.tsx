"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { StatusPill } from "@/components/ui/status-pill";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import {
  PolicyOverride,
  useAllowedRepos, useClassify, usePolicyOverrides,
  useRemovePolicyOverride, useSetPolicyOverride,
} from "@/lib/use-policy";

const SYSTEMS = ["slack", "github", "atlassian", "http"];

export default function PolicyPage() {
  const { data: overrides, isLoading, isError, refetch } = usePolicyOverrides();
  const setOverride = useSetPolicyOverride();
  const removeOverride = useRemovePolicyOverride();
  const classify = useClassify();
  const { data: repos } = useAllowedRepos();

  const [system, setSystem] = useState("");
  const [method, setMethod] = useState("");
  const [verdict, setVerdict] = useState("gate");
  const [reason, setReason] = useState("");
  const [confirmSet, setConfirmSet] = useState(false);
  const [pendingRemove, setPendingRemove] = useState<PolicyOverride | null>(null);

  const [testSystem, setTestSystem] = useState("");
  const [testMethod, setTestMethod] = useState("");
  const [testResult, setTestResult] = useState<{ verdict: string; reason: string } | null>(null);

  function doSetOverride() {
    setOverride.mutate({ system, method, verdict, reason }, {
      onSuccess: () => { setSystem(""); setMethod(""); setReason(""); setVerdict("gate"); },
    });
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-lg tracking-tight">Policy</h1>
        <p className="text-sm text-muted-foreground">What runs freely, what waits for a human, what never runs</p>
      </div>

      <div className="rounded-xl border bg-card shadow-sm">
        <div className="border-b px-4 py-2.5 text-sm font-semibold">Overrides</div>
        {isLoading && <LoadingState rows={1} />}
        {isError && <ErrorState onRetry={() => refetch()} message="Couldn't load overrides — try again." />}
        {!isLoading && !isError && !overrides?.length && (
          <EmptyState title="No overrides set" message="Everything runs on its default rules." />
        )}
        {!isLoading && !isError && overrides?.map((o) => (
          <div key={`${o.system}:${o.method}`} className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
            <span className="font-mono text-xs text-muted-foreground">{o.system}</span>
            <span className="font-mono text-xs">{o.method}</span>
            <StatusPill status={o.verdict} />
            <div className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{o.reason}</div>
            <Button size="sm" variant="ghost" onClick={() => setPendingRemove(o)}>
              Remove
            </Button>
          </div>
        ))}
      </div>

      <div className="max-w-lg space-y-3 rounded-xl border bg-card p-4 shadow-sm">
        <div className="text-sm font-semibold">Set an override</div>
        <select className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" value={system} onChange={(e) => setSystem(e.target.value)}>
          <option value="">Pick a system…</option>
          {SYSTEMS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" placeholder="Method (e.g. PUT)" value={method} onChange={(e) => setMethod(e.target.value)} />
        <select className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" value={verdict} onChange={(e) => setVerdict(e.target.value)}>
          <option value="allow">Allow</option>
          <option value="gate">Gate</option>
          <option value="deny">Deny</option>
        </select>
        <input className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" placeholder="Why (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
        <Button
          disabled={!system || !method || !reason || setOverride.isPending}
          onClick={() => { if (verdict === "allow") setConfirmSet(true); else doSetOverride(); }}
        >
          Set override
        </Button>
      </div>

      <div className="max-w-lg space-y-3 rounded-xl border bg-card p-4 shadow-sm">
        <div className="text-sm font-semibold">Test a classification</div>
        <select className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" value={testSystem} onChange={(e) => setTestSystem(e.target.value)}>
          <option value="">Pick a system…</option>
          {SYSTEMS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" placeholder="Method" value={testMethod} onChange={(e) => setTestMethod(e.target.value)} />
        <Button
          disabled={!testSystem || !testMethod || classify.isPending}
          onClick={() => classify.mutate({ system: testSystem, method: testMethod }, { onSuccess: setTestResult })}
        >
          Check
        </Button>
        {testResult && (
          <div className="rounded-md border bg-muted p-2.5 text-sm">
            <StatusPill status={testResult.verdict} />
            <span className="ml-2 text-muted-foreground">{testResult.reason}</span>
          </div>
        )}
      </div>

      <div className="max-w-lg rounded-xl border bg-card shadow-sm">
        <div className="border-b px-4 py-2.5 text-sm font-semibold">Repo allowlist <span className="font-normal text-muted-foreground">— set via ALLOWED_POST_REPOS, restart required to change</span></div>
        <div className="flex flex-wrap gap-2 p-4">
          {repos?.map((r) => <Badge key={r} variant="outline">{r}</Badge>)}
          {repos?.length === 0 && <span className="text-sm text-muted-foreground">None configured.</span>}
        </div>
      </div>

      <ConfirmDialog
        open={confirmSet}
        onOpenChange={setConfirmSet}
        title="Remove the human gate?"
        description={`Bott will be able to run ${system || "this"} ${method} without anyone approving first. You can switch this back anytime.`}
        confirmLabel="Set to allow"
        tone="danger"
        onConfirm={doSetOverride}
      />

      <ConfirmDialog
        open={!!pendingRemove}
        onOpenChange={(open) => { if (!open) setPendingRemove(null); }}
        title={pendingRemove?.verdict === "gate" ? "Remove the human gate?" : "Remove this override?"}
        description={
          pendingRemove
            ? pendingRemove.verdict === "gate"
              ? `Removing this override means Bott may run ${pendingRemove.system} ${pendingRemove.method} without waiting for a human. You can add the gate back anytime.`
              : `${pendingRemove.system} ${pendingRemove.method} will fall back to its default rule. You can set this override again anytime.`
            : undefined
        }
        confirmLabel="Remove override"
        tone={pendingRemove?.verdict === "gate" ? "danger" : "default"}
        onConfirm={() => { if (pendingRemove) removeOverride.mutate({ system: pendingRemove.system, method: pendingRemove.method }); }}
      />
    </div>
  );
}
