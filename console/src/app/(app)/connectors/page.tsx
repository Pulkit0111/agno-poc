"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { StatusPill } from "@/components/ui/status-pill";
import type { ConnectorStatus } from "@/lib/use-connectors";
import { useConnectors, useTestConnector } from "@/lib/use-connectors";
import { useMe } from "@/lib/use-me";

// Connectors with a live probe wired up on the backend (src/bott/skills/connectors/probes.py).
// GitHub and Spin have config checks but no cheap authenticated round-trip yet — they still
// get "Fix setup" steps, just no Test button (nothing to call).
const TESTABLE = new Set(["jira", "confluence", "slack", "memra", "sentry", "google", "codex"]);

function isTestable(name: string): boolean {
  return TESTABLE.has(name.toLowerCase());
}

function FixSetupDrawer({
  connector,
  onOpenChange,
}: {
  connector: ConnectorStatus | null;
  onOpenChange: (open: boolean) => void;
}) {
  const test = useTestConnector();

  function close() {
    onOpenChange(false);
    test.reset();
  }

  return (
    <Sheet open={connector !== null} onOpenChange={(open) => { if (!open) close(); }}>
      <SheetContent className="w-[420px] sm:max-w-[460px]">
        <SheetHeader>
          <SheetTitle className="text-base">{connector?.name} — fix setup</SheetTitle>
        </SheetHeader>
        {connector && (
          <div className="space-y-4 px-4 text-sm">
            <p className="text-xs text-muted-foreground">{connector.off}</p>
            {!!connector.fix?.length && (
              <ol className="list-decimal space-y-2 pl-4 text-sm">
                {connector.fix.map((step, i) => <li key={i}>{step}</li>)}
              </ol>
            )}
            {test.data && (
              <div className="flex items-start gap-2 rounded-lg border p-3">
                <StatusPill
                  tone={test.data.ok ? "good" : "bad"}
                  label={test.data.ok ? "Connected" : "Still unreachable"}
                />
                <p className="text-xs text-muted-foreground">{test.data.message}</p>
              </div>
            )}
          </div>
        )}
        <SheetFooter className="flex-row justify-end">
          <Button variant="outline" onClick={close}>Close</Button>
          {connector && isTestable(connector.name) && (
            <Button
              disabled={test.isPending}
              onClick={() => test.mutate(connector.name)}
            >
              Test connection
            </Button>
          )}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function ConnectorCard({
  connector,
  isAdmin,
  onFixSetup,
}: {
  connector: ConnectorStatus;
  isAdmin: boolean;
  onFixSetup: () => void;
}) {
  const test = useTestConnector();

  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold">{connector.name}</span>
        <span className="ml-auto">
          {connector.ok
            ? <StatusPill tone="good" label="Connected" />
            : <StatusPill tone="bad" label="Unavailable" />}
        </span>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {connector.ok ? connector.on : (isAdmin ? connector.off : "Ask an admin to reconnect this.")}
      </p>
      {isAdmin && (
        <div className="mt-3 flex items-center gap-2">
          {!connector.ok && (
            <Button size="sm" variant="outline" onClick={onFixSetup}>Fix setup</Button>
          )}
          {connector.ok && isTestable(connector.name) && (
            <Button
              size="sm"
              variant="ghost"
              disabled={test.isPending}
              onClick={() => test.mutate(connector.name)}
            >
              Test
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

export default function ConnectorsPage() {
  const { data: me } = useMe();
  const { data: connectors, isLoading, isError, refetch } = useConnectors();
  const [fixTarget, setFixTarget] = useState<ConnectorStatus | null>(null);

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
            <ConnectorCard
              key={c.name}
              connector={c}
              isAdmin={!!me?.is_admin}
              onFixSetup={() => setFixTarget(c)}
            />
          ))}
        </div>
      )}

      <FixSetupDrawer
        connector={fixTarget}
        onOpenChange={(open) => { if (!open) setFixTarget(null); }}
      />
    </div>
  );
}
