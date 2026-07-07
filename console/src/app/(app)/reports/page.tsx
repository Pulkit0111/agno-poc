"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useRunReport } from "@/lib/use-reports";
import { useMe } from "@/lib/use-me";

type ReportDef = {
  kind: string;
  label: string;
  fields: readonly string[];
};

const REPORTS: readonly ReportDef[] = [
  { kind: "security", label: "Security check", fields: [] },
  { kind: "portfolio", label: "Portfolio snapshot", fields: [] },
  { kind: "sprint_snapshot", label: "Sprint snapshot", fields: ["engagement"] },
  { kind: "engagement_status", label: "Engagement status", fields: ["engagement"] },
  { kind: "standup_open", label: "Open standup", fields: ["team", "channel"] },
  { kind: "standup_close", label: "Close standup", fields: ["team", "channel"] },
  { kind: "standup_summary", label: "Post call summary", fields: ["team", "channel"] },
];

export default function ReportsPage() {
  const { data: me } = useMe();
  const run = useRunReport();
  const [active, setActive] = useState<ReportDef | null>(null);
  const [engagement, setEngagement] = useState("");
  const [team, setTeam] = useState("");
  const [channel, setChannel] = useState("");
  const [result, setResult] = useState<string | null>(null);

  function submit() {
    if (!active) return;
    run.mutate(
      { kind: active.kind, engagement: engagement || undefined, team: team || undefined, channel: channel || undefined },
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
            onClick={() => { setActive(r); setResult(null); }}
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
          {active.fields.includes("engagement") && (
            <input className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" placeholder="Engagement (e.g. acme-commerce)" value={engagement} onChange={(e) => setEngagement(e.target.value)} />
          )}
          {active.fields.includes("team") && (
            <input className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" placeholder="Team" value={team} onChange={(e) => setTeam(e.target.value)} />
          )}
          {active.fields.includes("channel") && (
            <input className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" placeholder="#channel" value={channel} onChange={(e) => setChannel(e.target.value)} />
          )}
          <Button onClick={submit} disabled={run.isPending}>
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
