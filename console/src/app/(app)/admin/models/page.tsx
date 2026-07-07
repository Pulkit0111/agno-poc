"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { CodexConnect } from "@/components/system/codex-connect";
import { useModels, useSetModelOverride } from "@/lib/use-models";

const ROLES = [
  { key: "chat", label: "Chat", hint: "answers, digests, agendas" },
  { key: "build", label: "Build", hint: "writes code, opens PRs" },
  { key: "review", label: "Review", hint: "judges PRs — must not share build's weights" },
] as const;

export default function ModelsPage() {
  const { data, isLoading } = useModels();
  const setOverride = useSetModelOverride();

  if (isLoading || !data) {
    return <div className="space-y-3"><Skeleton className="h-24" /><Skeleton className="h-24" /></div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Models</h1>
        <p className="text-sm text-muted-foreground">Which model does which job — chat, build, review</p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {ROLES.map((role) => {
          const current = data[role.key];
          const isConflict = role.key === "review" && data.conflict;
          return (
            <div key={role.key} className={`rounded-xl border bg-card p-4 shadow-sm ${isConflict ? "border-amber-500/40" : ""}`}>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {role.label}
                {isConflict && <Badge variant="outline" className="text-amber-700 dark:text-amber-400">conflict</Badge>}
              </div>
              <div className="mt-2 font-mono text-sm">{current}</div>
              <div className="mt-1 text-xs text-muted-foreground">{role.hint}</div>
              <select
                className="mt-3 w-full rounded-md border bg-background px-2.5 py-1.5 font-mono text-xs"
                value={current}
                onChange={(e) => setOverride.mutate({ key: `model.${role.key}`, value: e.target.value })}
              >
                {data.providers.find((p) => p.name === data.provider)?.models.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
          );
        })}
      </div>

      {data.conflict && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-muted-foreground">
          <span className="font-medium text-amber-700 dark:text-amber-400">Review currently equals Build.</span>{" "}
          {data.swap_preview
            ? <>The reviewer would judge its own author&apos;s work — anti-affinity will auto-swap review to <span className="font-mono">{data.swap_preview}</span> at run time.</>
            : "No safe alternate model was found — review will run against the same weights as build."}
        </div>
      )}

      <div className="rounded-xl border bg-card shadow-sm">
        <div className="border-b px-4 py-2.5 text-sm font-semibold">Providers</div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="px-4 py-2 font-medium">Provider</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Models</th>
            </tr>
          </thead>
          <tbody>
            {data.providers.map((p) => (
              <tr key={p.name} className="border-t">
                <td className="px-4 py-2 font-medium capitalize">{p.name}</td>
                <td className="px-4 py-2">
                  <Badge variant="outline" className={p.usable ? "text-green-700 dark:text-green-400" : "text-muted-foreground"}>
                    {p.usable ? "Healthy" : p.hint}
                  </Badge>
                </td>
                <td className="px-4 py-2 text-xs text-muted-foreground">{p.models.length || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CodexConnect connected={data.providers.find((p) => p.name === "codex")?.usable ?? false} />

      {data.codex_usage && (
        <div className="max-w-lg rounded-xl border bg-card p-4 shadow-sm">
          <div className="mb-2 text-sm font-semibold">Codex usage (last hour)</div>
          <p className="text-xs text-muted-foreground">
            Everyone shares this one login — watch this if replies start slowing down or erroring.
          </p>
          <div className="mt-3 flex gap-6">
            <div>
              <div className="text-2xl font-semibold">{data.codex_usage.requests}</div>
              <div className="text-xs text-muted-foreground">requests</div>
            </div>
            <div>
              <div className="text-2xl font-semibold">{data.codex_usage.output_tokens.toLocaleString()}</div>
              <div className="text-xs text-muted-foreground">output tokens</div>
            </div>
          </div>
          {data.codex_usage.top_users.length > 0 && (
            <div className="mt-3 border-t pt-3">
              <div className="mb-1 text-xs font-medium text-muted-foreground">Busiest users</div>
              <ul className="space-y-0.5 text-xs">
                {data.codex_usage.top_users.map((u) => (
                  <li key={u.user_id} className="flex justify-between">
                    <span className="text-muted-foreground">{u.user_id}</span>
                    <span className="font-mono">{u.requests}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
