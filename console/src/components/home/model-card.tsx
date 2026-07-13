"use client";

import Link from "next/link";
import { useMe } from "@/lib/use-me";
import { getActiveModels, useModels } from "@/lib/use-models";

/**
 * Home-page card for the one thing everything depends on: the ChatGPT (Codex)
 * connection, plus which model plays which of the three roles. Shown to
 * everyone — Task 2 trims the member payload down to `{active, providers}`
 * while admins still get the flat shape; `getActiveModels` reads either.
 */
export function ModelCard() {
  const { data: me } = useMe();
  const { data, isLoading, isError } = useModels();

  if (isLoading || isError || !data) return null;

  const active = getActiveModels(data);
  const connected = data.providers.find((p) => p.name === "codex")?.usable ?? false;

  const ROLES = [
    { key: "chat" as const, label: "Chat — answers you in Slack" },
    { key: "build" as const, label: "Build — writes code for approved jobs" },
    { key: "review" as const, label: "Review — checks PRs (always ≠ Build)" },
  ];

  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
            connected
              ? "bg-green-500/15 text-green-700 dark:text-green-400"
              : "bg-red-500/15 text-red-700 dark:text-red-400"
          }`}
        >
          <span className={`size-1.5 rounded-full ${connected ? "bg-green-500" : "bg-red-500"}`} />
          {connected ? "ChatGPT (Codex) connected" : "ChatGPT (Codex) not connected"}
        </span>
        {me?.is_admin && (
          <Link href="/admin/models" className="ml-auto text-xs text-primary hover:underline">
            Manage models →
          </Link>
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-6">
        {ROLES.map((role) => (
          <div key={role.key}>
            <div className="font-mono text-xs font-semibold">{active[role.key]}</div>
            <div className="text-[10.5px] text-muted-foreground">{role.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
