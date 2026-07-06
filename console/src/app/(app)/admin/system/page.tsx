"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ReviewTrendsChart } from "@/components/system/review-trends-chart";
import { useReviewTrends, useSystemStatus } from "@/lib/use-system";

export default function SystemPage() {
  const { data: status, isLoading } = useSystemStatus();
  const { data: byWeek, isLoading: trendsLoading } = useReviewTrends(56);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">System</h1>
        <p className="text-sm text-muted-foreground">Health, advisories, and how reviews are trending</p>
      </div>

      {isLoading || !status ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4"><Skeleton className="h-20" /><Skeleton className="h-20" /></div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-xl border bg-card p-4 shadow-sm">
            <div className="text-xs font-medium text-muted-foreground">Database</div>
            <div className="mt-1 text-sm font-semibold capitalize">{status.database.kind}</div>
          </div>
          <div className="rounded-xl border bg-card p-4 shadow-sm">
            <div className="text-xs font-medium text-muted-foreground">Slack</div>
            <div className="mt-1 text-sm font-semibold">{status.slack_configured ? "Configured" : "Not configured"}</div>
          </div>
          <div className="rounded-xl border bg-card p-4 shadow-sm">
            <div className="text-xs font-medium text-muted-foreground">GitHub</div>
            <div className="mt-1 text-sm font-semibold">{status.github_configured ? "Configured" : "Not configured"}</div>
          </div>
          <div className="rounded-xl border bg-card p-4 shadow-sm">
            <div className="text-xs font-medium text-muted-foreground">Admins</div>
            <div className="mt-1 text-sm font-semibold">{status.admins_count}</div>
          </div>
        </div>
      )}

      {status && (
        <div className="rounded-xl border bg-card shadow-sm">
          <div className="border-b px-4 py-2.5 text-sm font-semibold">Connectors</div>
          <div className="flex flex-wrap gap-2 p-4">
            {Object.entries(status.connectors).map(([name, ok]) => (
              <Badge key={name} variant="outline" className={ok ? "text-green-700 dark:text-green-400" : "text-muted-foreground"}>
                {name} {ok ? "✓" : "✗"}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {status && status.advisories.length > 0 && (
        <div className="rounded-xl border bg-card shadow-sm">
          <div className="border-b px-4 py-2.5 text-sm font-semibold">Advisories</div>
          <ul>
            {status.advisories.map((a) => (
              <li key={a.name} className="border-b px-4 py-2.5 text-sm last:border-b-0">{a.message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-xl border bg-card shadow-sm">
        <div className="border-b px-4 py-2.5 text-sm font-semibold">Review verdicts by week</div>
        <div className="p-4">
          {trendsLoading || !byWeek ? <Skeleton className="h-44" /> : <ReviewTrendsChart byWeek={byWeek} />}
        </div>
      </div>
    </div>
  );
}
