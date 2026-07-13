"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { StatusPill } from "@/components/ui/status-pill";
import { ApiError } from "@/lib/api";
import type { ConnectorStatus, ConnectorType } from "@/lib/use-connectors";
import {
  connectorLabel, useAddConnector, useConnectors, useRemoveConnector, useTestConnector,
} from "@/lib/use-connectors";
import { useMe } from "@/lib/use-me";

// The fixed cards connector_statuses() always returns — anything else in the list is a
// connector added from the console (connector_credentials store), which is removable and
// (per the naming convention probes.py understands: github-app / sentry-<org> / http-<slug>)
// always testable.
const STATIC_NAMES = new Set(["slack", "github", "jira", "confluence", "memra", "spin", "sentry", "google", "codex"]);

// Static connectors with a config check but no cheap authenticated round-trip yet — they
// still get "Fix setup" steps, just no Test button (nothing to call). Everything else
// (including every console-added connector) has a live probe.
const NOT_TESTABLE = new Set(["github", "spin"]);

function isTestable(name: string): boolean {
  return !NOT_TESTABLE.has(name.toLowerCase());
}

function isRemovable(name: string): boolean {
  return !STATIC_NAMES.has(name.toLowerCase());
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
  onRemove,
}: {
  connector: ConnectorStatus;
  isAdmin: boolean;
  onFixSetup: () => void;
  onRemove: () => void;
}) {
  const test = useTestConnector();
  const removable = isAdmin && isRemovable(connector.name);

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
          {removable && (
            <Button
              size="sm"
              variant="ghost"
              className="ml-auto text-red-600 hover:text-red-700 dark:text-red-400"
              onClick={onRemove}
            >
              Remove
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

const CONNECTOR_TYPES: { value: ConnectorType; label: string }[] = [
  { value: "github_app", label: "GitHub (org app)" },
  { value: "sentry_org", label: "Sentry (second org)" },
  { value: "http_api", label: "Custom HTTP API" },
];

function AddConnectorDrawer({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const add = useAddConnector();
  const [type, setType] = useState<ConnectorType | null>(null);

  const [appId, setAppId] = useState("");
  const [installationId, setInstallationId] = useState("");
  const [privateKey, setPrivateKey] = useState("");

  const [org, setOrg] = useState("");
  const [authToken, setAuthToken] = useState("");
  const [sentryBaseUrl, setSentryBaseUrl] = useState("");

  const [slug, setSlug] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [headerName, setHeaderName] = useState("");
  const [headerValue, setHeaderValue] = useState("");

  function reset() {
    setType(null);
    setAppId(""); setInstallationId(""); setPrivateKey("");
    setOrg(""); setAuthToken(""); setSentryBaseUrl("");
    setSlug(""); setBaseUrl(""); setHeaderName(""); setHeaderValue("");
    add.reset();
  }

  function close() {
    onOpenChange(false);
    reset();
  }

  function fieldsFor(t: ConnectorType): Record<string, string> {
    if (t === "github_app") return { app_id: appId, installation_id: installationId, private_key: privateKey };
    if (t === "sentry_org") return { org, auth_token: authToken, base_url: sentryBaseUrl };
    return { name: slug, base_url: baseUrl, header_name: headerName, header_value: headerValue };
  }

  function canSubmit(): boolean {
    if (type === "github_app") return !!appId && !!privateKey;
    if (type === "sentry_org") return !!org && !!authToken;
    if (type === "http_api") return !!slug && !!baseUrl;
    return false;
  }

  const errorMessage = add.error instanceof ApiError ? add.error.message : null;

  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) close(); }}>
      <SheetContent className="w-[420px] sm:max-w-[460px]">
        <SheetHeader>
          <SheetTitle className="text-base">Add connector</SheetTitle>
        </SheetHeader>
        <div className="space-y-4 px-4 text-sm">
          {!type && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">What are we connecting?</p>
              {CONNECTOR_TYPES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => setType(t.value)}
                  className="w-full rounded-lg border p-3 text-left text-sm hover:bg-muted"
                >
                  {t.label}
                </button>
              ))}
            </div>
          )}

          {type === "github_app" && (
            <div className="space-y-3">
              <input
                className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
                placeholder="App ID" value={appId} onChange={(e) => setAppId(e.target.value)}
              />
              <input
                className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
                placeholder="Installation ID (optional)" value={installationId}
                onChange={(e) => setInstallationId(e.target.value)}
              />
              <textarea
                className="h-32 w-full rounded-md border bg-background px-2.5 py-1.5 font-mono text-xs"
                placeholder="Private key (PEM)" value={privateKey}
                onChange={(e) => setPrivateKey(e.target.value)}
              />
            </div>
          )}

          {type === "sentry_org" && (
            <div className="space-y-3">
              <input
                className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
                placeholder="Org slug" value={org} onChange={(e) => setOrg(e.target.value)}
              />
              <input
                type="password"
                className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
                placeholder="Auth token" value={authToken} onChange={(e) => setAuthToken(e.target.value)}
              />
              <input
                className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
                placeholder="Base URL (optional — defaults to sentry.io)" value={sentryBaseUrl}
                onChange={(e) => setSentryBaseUrl(e.target.value)}
              />
            </div>
          )}

          {type === "http_api" && (
            <div className="space-y-3">
              <input
                className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
                placeholder="Name/slug" value={slug} onChange={(e) => setSlug(e.target.value)}
              />
              <input
                className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
                placeholder="Base URL" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
              />
              <input
                className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
                placeholder="Header name (optional)" value={headerName} onChange={(e) => setHeaderName(e.target.value)}
              />
              <input
                type="password"
                className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
                placeholder="Header value (optional)" value={headerValue} onChange={(e) => setHeaderValue(e.target.value)}
              />
            </div>
          )}

          {errorMessage && (
            <div className="rounded-lg border border-red-600/30 bg-red-500/5 p-3 text-xs text-red-700 dark:text-red-400">
              {errorMessage}
            </div>
          )}
        </div>
        <SheetFooter className="flex-row justify-end">
          <Button variant="outline" onClick={close}>Close</Button>
          {type && (
            <Button
              disabled={!canSubmit() || add.isPending}
              onClick={() => add.mutate({ type, fields: fieldsFor(type) }, { onSuccess: close })}
            >
              Connect &amp; test
            </Button>
          )}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

export default function ConnectorsPage() {
  const { data: me } = useMe();
  const { data: connectors, isLoading, isError, refetch } = useConnectors();
  const [fixTarget, setFixTarget] = useState<ConnectorStatus | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<ConnectorStatus | null>(null);
  const remove = useRemoveConnector();

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-lg tracking-tight">Connectors</h1>
          <p className="text-sm text-muted-foreground">What Bott can reach on your behalf</p>
        </div>
        {!!me?.is_admin && (
          <Button size="sm" onClick={() => setAddOpen(true)}>Add connector</Button>
        )}
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
              onRemove={() => setRemoveTarget(c)}
            />
          ))}
        </div>
      )}

      <FixSetupDrawer
        connector={fixTarget}
        onOpenChange={(open) => { if (!open) setFixTarget(null); }}
      />

      <AddConnectorDrawer open={addOpen} onOpenChange={setAddOpen} />

      <ConfirmDialog
        open={!!removeTarget}
        onOpenChange={(open) => { if (!open) setRemoveTarget(null); }}
        title="Remove this connector?"
        description={
          removeTarget
            ? `Bott loses access via ${removeTarget.name} immediately. You can add it again anytime.`
            : undefined
        }
        confirmLabel="Remove"
        tone="danger"
        onConfirm={() => { if (removeTarget) remove.mutate(removeTarget.name); }}
      />
    </div>
  );
}
