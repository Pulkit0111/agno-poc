"use client";

import { EmptyState, ErrorState, LoadingState, NoAccessState } from "@/components/common/states";
import { Time } from "@/lib/time";
import { isForbidden } from "@/lib/api";
import { useHealth, type HealthConnector } from "@/lib/use-health";
import { useMe } from "@/lib/use-me";

function StatTile({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string | number;
  tone?: "good" | "bad";
  hint?: string;
}) {
  const toneClass =
    tone === "good"
      ? "text-green-700 dark:text-green-400"
      : tone === "bad"
        ? "text-red-700 dark:text-red-400"
        : "";
  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold tracking-tight ${toneClass}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

function Dot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block size-2 flex-none rounded-full ${ok ? "bg-green-500" : "bg-red-500"}`}
      aria-hidden
    />
  );
}

export default function HealthPage() {
  const { data: me, isLoading: meLoading } = useMe();
  const { data: health, isLoading, isError, error, refetch } = useHealth();

  if (meLoading) return <LoadingState rows={5} />;
  if (!me?.is_admin) return <NoAccessState />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Health</h1>
        <p className="text-sm text-muted-foreground">
          One place to see if Bott and everything it depends on is working
        </p>
      </div>

      {isLoading ? (
        <LoadingState rows={4} />
      ) : isError ? (
        isForbidden(error) ? (
          <NoAccessState />
        ) : (
          <ErrorState message="Couldn't load health." onRetry={() => refetch()} />
        )
      ) : !health ? null : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile
              label="Model"
              value={health.model.connected ? "Connected" : "Not connected"}
              tone={health.model.connected ? "good" : "bad"}
              hint={health.model.provider}
            />
            <StatTile label="Jobs running" value={health.jobs.running} />
            <StatTile
              label="Jobs failed (24h)"
              value={health.jobs.failed_24h}
              tone={health.jobs.failed_24h > 0 ? "bad" : undefined}
            />
            <StatTile label="Queue waiting" value={health.jobs.queued} />
          </div>

          <div className="rounded-xl border bg-card shadow-sm">
            <div className="flex flex-col gap-0.5 border-b px-4 py-2.5">
              <div className="text-sm font-semibold">Connectors</div>
              <div className="text-xs text-muted-foreground">Shows whether each connector is configured</div>
            </div>
            {health.connectors.length === 0 ? (
              <EmptyState title="No connectors" message="Nothing is wired up yet." />
            ) : (
              <ul>
                {health.connectors.map((c: HealthConnector) => {
                  const ok = c.connected !== false && !c.off;
                  return (
                    <li
                      key={c.name}
                      className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0"
                    >
                      <Dot ok={ok} />
                      <div className="min-w-0 flex-1 truncate text-sm font-medium">{c.name}</div>
                      {!ok && c.off && (
                        <div className="max-w-[60%] truncate text-right text-xs text-muted-foreground">
                          {c.off}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="rounded-xl border bg-card shadow-sm">
            <div className="border-b px-4 py-2.5 text-sm font-semibold">GitHub webhook</div>
            <div className="flex items-center gap-2 px-4 py-3 text-sm">
              {health.webhook.last_received_at !== null ? (
                <span className="text-muted-foreground">
                  Last event received <Time value={health.webhook.last_received_at} />
                </span>
              ) : (
                <span className="text-muted-foreground">No events received yet</span>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
