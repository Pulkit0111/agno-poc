"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useRunReport } from "@/lib/use-reports";
import { useMe } from "@/lib/use-me";

type ReportDef = {
  kind: string;
  label: string;
  hint: string;
  needsEngagement?: boolean;
};

const REPORTS: readonly ReportDef[] = [
  { kind: "security", label: "Security check", hint: "Open vulnerabilities and exposure across the estate" },
  { kind: "portfolio", label: "Portfolio snapshot", hint: "Health across every active engagement" },
  { kind: "sprint_snapshot", label: "Sprint snapshot", hint: "Where the current sprint stands", needsEngagement: true },
  { kind: "engagement_status", label: "Engagement status", hint: "Full status for one engagement", needsEngagement: true },
];

export default function ReportsPage() {
  const { data: me } = useMe();
  const run = useRunReport();
  const [active, setActive] = useState<ReportDef | null>(null);
  const [engagement, setEngagement] = useState("");
  const [result, setResult] = useState<string | null>(null);

  function submit() {
    if (!active) return;
    run.mutate(
      { kind: active.kind, engagement: engagement || undefined },
      { onSuccess: (data) => setResult(data.result) },
    );
  }

  if (me && !me.is_admin) {
    return (
      <div className="space-y-4">
        <h1 className="text-lg font-semibold tracking-tight">Reports</h1>
        <p className="text-sm text-muted-foreground">
          Running reports on demand needs an admin — ask one if you need something run.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Reports</h1>
        <p className="text-sm text-muted-foreground">Run any report now — the result appears below</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {REPORTS.map((r) => (
          <button
            key={r.kind}
            onClick={() => { setActive(r); setResult(null); setEngagement(""); }}
            className={`rounded-full border px-3 py-1.5 text-sm font-medium ${
              active?.kind === r.kind ? "border-primary/40 bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>
      {active && (
        <div className="max-w-lg space-y-3 rounded-xl border bg-card p-4 shadow-sm">
          <p className="text-sm text-muted-foreground">{active.hint}</p>
          {active.needsEngagement && (
            <input
              className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
              placeholder="Engagement (e.g. acme-commerce)"
              value={engagement}
              onChange={(e) => setEngagement(e.target.value)}
            />
          )}
          <Button onClick={submit} disabled={run.isPending || (active.needsEngagement && !engagement)}>
            {run.isPending ? "Running…" : `Run ${active.label}`}
          </Button>
        </div>
      )}
      {result && (
        <div className="rounded-xl border bg-card p-4 shadow-sm">
          <div className="mb-2 text-xs font-medium text-muted-foreground">Result</div>
          <pre className="whitespace-pre-wrap text-sm">{result}</pre>
        </div>
      )}
    </div>
  );
}
