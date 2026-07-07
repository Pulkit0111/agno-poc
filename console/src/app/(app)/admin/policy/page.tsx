"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useAllowedRepos, useClassify, usePolicyOverrides,
  useRemovePolicyOverride, useSetPolicyOverride,
} from "@/lib/use-policy";

const VERDICT_STYLE: Record<string, string> = {
  allow: "text-green-700 dark:text-green-400",
  gate: "text-amber-700 dark:text-amber-400",
  deny: "text-destructive",
};

const SYSTEMS = ["slack", "github", "atlassian", "http"];

export default function PolicyPage() {
  const { data: overrides, isLoading, isError } = usePolicyOverrides();
  const setOverride = useSetPolicyOverride();
  const removeOverride = useRemovePolicyOverride();
  const classify = useClassify();
  const { data: repos } = useAllowedRepos();

  const [system, setSystem] = useState("");
  const [method, setMethod] = useState("");
  const [verdict, setVerdict] = useState("gate");
  const [reason, setReason] = useState("");

  const [testSystem, setTestSystem] = useState("");
  const [testMethod, setTestMethod] = useState("");
  const [testResult, setTestResult] = useState<{ verdict: string; reason: string } | null>(null);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Policy</h1>
        <p className="text-sm text-muted-foreground">What runs freely, what waits for a human, what never runs</p>
      </div>

      <div className="rounded-xl border bg-card shadow-sm">
        <div className="border-b px-4 py-2.5 text-sm font-semibold">Overrides</div>
        {isLoading && <div className="space-y-2 p-4"><Skeleton className="h-9" /></div>}
        {isError && <div className="px-4 py-8 text-center text-sm text-destructive">Couldn&apos;t load — try refreshing the page.</div>}
        {!isLoading && !isError && !overrides?.length && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">No overrides set — everything runs on its default rules.</div>
        )}
        {overrides?.map((o) => (
          <div key={`${o.system}:${o.method}`} className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
            <span className="font-mono text-xs text-muted-foreground">{o.system}</span>
            <span className="font-mono text-xs">{o.method}</span>
            <Badge variant="outline" className={VERDICT_STYLE[o.verdict]}>{o.verdict}</Badge>
            <div className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{o.reason}</div>
            <Button size="sm" variant="ghost" onClick={() => removeOverride.mutate({ system: o.system, method: o.method })}>
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
          onClick={() => setOverride.mutate({ system, method, verdict, reason }, {
            onSuccess: () => { setSystem(""); setMethod(""); setReason(""); setVerdict("gate"); },
          })}
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
            <Badge variant="outline" className={VERDICT_STYLE[testResult.verdict]}>{testResult.verdict}</Badge>
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
    </div>
  );
}
