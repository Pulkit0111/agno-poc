"use client";

import Link from "next/link";
import { TriangleAlert } from "lucide-react";
import { useMe } from "@/lib/use-me";
import { useModels } from "@/lib/use-models";

/**
 * Home-page tile for the one thing everything depends on: the ChatGPT (Codex)
 * connection. Connected → a quiet one-liner. Not connected → a loud warning,
 * because Bott is dead in the water until an admin fixes it.
 *
 * Status comes from the same GET /api/console/v1/models query the Models page
 * uses (shared react-query cache key). For members the backend returns a
 * trimmed response (codex connected or not — no hints, usage, or catalog),
 * which is exactly what this banner needs.
 */
export function CodexStatusBanner() {
  const { data: me } = useMe();
  const { data, isLoading, isError } = useModels();

  if (isLoading || isError || !data) return null;

  const connected = data.providers.find((p) => p.name === "codex")?.usable ?? false;

  if (connected) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground" data-testid="codex-status">
        <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
        <span>Model: ChatGPT (Codex) — connected</span>
      </div>
    );
  }

  return (
    <div
      className="flex flex-wrap items-center gap-3 rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm shadow-sm"
      data-testid="codex-status"
    >
      <TriangleAlert className="size-4 flex-none text-red-600 dark:text-red-400" />
      <div className="min-w-0 flex-1">
        <div className="font-medium text-red-700 dark:text-red-400">Bott has no model connection</div>
        <div className="text-xs text-muted-foreground">
          Nothing will work until an admin connects ChatGPT.
        </div>
      </div>
      {me?.is_admin ? (
        <Link
          href="/admin/models"
          className="flex-none rounded-md border bg-background px-3 py-1.5 text-xs font-medium hover:border-foreground/20"
        >
          Connect ChatGPT
        </Link>
      ) : (
        <span className="flex-none text-xs text-muted-foreground">Ask an admin to connect it.</span>
      )}
    </div>
  );
}
