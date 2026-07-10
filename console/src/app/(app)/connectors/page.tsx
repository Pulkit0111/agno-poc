"use client";

import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { StatusPill } from "@/components/ui/status-pill";
import { useConnectors } from "@/lib/use-connectors";
import { useMe } from "@/lib/use-me";

export default function ConnectorsPage() {
  const { data: me } = useMe();
  const { data: connectors, isLoading, isError, refetch } = useConnectors();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Connectors</h1>
        <p className="text-sm text-muted-foreground">What Bott can reach on your behalf</p>
      </div>

      {isLoading && <LoadingState rows={2} />}

      {isError && (
        <ErrorState
          onRetry={() => refetch()}
          message="Couldn't load connectors — check the connection and try again."
        />
      )}

      {!isLoading && !isError && !connectors?.length && (
        <EmptyState
          title="No connectors yet"
          message="Bott has nothing wired up to reach on your behalf right now."
        />
      )}

      {!isLoading && !isError && !!connectors?.length && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {connectors.map((c) => (
            <div key={c.name} className="rounded-xl border bg-card p-4 shadow-sm">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold">{c.name}</span>
                <span className="ml-auto">
                  {c.ok
                    ? <StatusPill tone="good" label="Connected" />
                    : <StatusPill tone="bad" label="Unavailable" />}
                </span>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {c.ok ? c.on : (me?.is_admin ? c.off : "Ask an admin to reconnect this.")}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
