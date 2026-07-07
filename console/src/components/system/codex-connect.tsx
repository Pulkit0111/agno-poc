"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  CodexLoginStart, useCodexLoginStatus, useConnectCodex,
  useDisconnectCodex, useStartCodexLogin,
} from "@/lib/use-models";

/**
 * Admin "Connect ChatGPT" card. Click Connect, get a verification URL + code, approve in a
 * browser — this flips to Connected on its own via polling. No manual auth.json copying.
 * Needs the `codex` CLI installed on whatever host runs the console API; if that's not
 * available, the "paste auth.json manually" fallback below still works.
 */
export function CodexConnect({ connected }: { connected: boolean }) {
  const qc = useQueryClient();
  const [device, setDevice] = useState<CodexLoginStart | null>(null);
  const [showPasteFallback, setShowPasteFallback] = useState(false);
  const [authJson, setAuthJson] = useState("");
  const [copied, setCopied] = useState(false);
  const start = useStartCodexLogin();
  const disconnect = useDisconnectCodex();
  const connectCodex = useConnectCodex();
  const status = useCodexLoginStatus(!!device && !connected);
  // The console's "connected" prop only updates when the /models query itself refetches;
  // fold in the live poll result too so this flips the instant the login succeeds, not
  // whenever something else happens to trigger a refetch.
  const effectivelyConnected = connected || !!status.data?.connected;

  useEffect(() => {
    if (status.data?.connected) qc.invalidateQueries({ queryKey: ["models"] });
  }, [status.data?.connected, qc]);

  const copyCode = async () => {
    if (!device?.code) return;
    try {
      await navigator.clipboard.writeText(device.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard may be unavailable — the code is still shown to select manually */
    }
  };

  return (
    <div className="max-w-lg rounded-xl border bg-card p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-semibold">ChatGPT / Codex subscription</div>
        <span className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
          <span className={`inline-block h-2 w-2 rounded-full ${effectivelyConnected ? "bg-green-500" : "bg-muted-foreground/30"}`} />
          {effectivelyConnected ? "connected" : "not connected"}
        </span>
      </div>

      {effectivelyConnected ? (
        <Button
          size="sm"
          variant="outline"
          disabled={disconnect.isPending}
          onClick={() => { setDevice(null); disconnect.mutate(); }}
        >
          Disconnect
        </Button>
      ) : device ? (
        <div className="space-y-2 rounded-md border bg-muted/30 p-3 text-sm">
          <p>Finish in your browser (device login — there&apos;s no redirect back):</p>
          {device.url && (
            <p>
              1. Open{" "}
              <a href={device.url} target="_blank" rel="noreferrer" className="font-medium text-primary underline">
                {device.url}
              </a>
            </p>
          )}
          {device.code && (
            <p className="flex items-center gap-2">
              <span>2. Enter code</span>
              <span className="rounded bg-background px-2 py-0.5 font-mono font-semibold">{device.code}</span>
              <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={copyCode}>
                {copied ? "Copied" : "Copy"}
              </Button>
            </p>
          )}
          <p className="text-xs text-muted-foreground">Approve, then come back here — it flips to Connected on its own.</p>
        </div>
      ) : (
        <div className="space-y-2">
          <Button
            size="sm"
            disabled={start.isPending}
            onClick={() => start.mutate(undefined, { onSuccess: (result) => setDevice(result) })}
          >
            {start.isPending ? "Starting…" : "Connect ChatGPT"}
          </Button>
          <button
            type="button"
            className="block text-xs text-muted-foreground underline"
            onClick={() => setShowPasteFallback((v) => !v)}
          >
            {showPasteFallback ? "Hide" : "Codex CLI not installed here? Paste auth.json instead"}
          </button>
        </div>
      )}

      {!effectivelyConnected && showPasteFallback && (
        <div className="mt-3 space-y-2 border-t pt-3">
          <textarea
            className="h-24 w-full rounded-md border bg-background px-2.5 py-1.5 font-mono text-xs"
            placeholder="Paste ~/.codex/auth.json contents"
            value={authJson}
            onChange={(e) => setAuthJson(e.target.value)}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={!authJson || connectCodex.isPending}
            onClick={() => connectCodex.mutate(authJson, { onSuccess: () => setAuthJson("") })}
          >
            Connect
          </Button>
        </div>
      )}
    </div>
  );
}
