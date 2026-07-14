"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { LoadingState, ErrorState, NoAccessState } from "@/components/common/states";
import { CodexConnect } from "@/components/system/codex-connect";
import { isForbidden } from "@/lib/api";
import {
  isAdminModels, ProviderName, useModels, useSetModelOverride,
} from "@/lib/use-models";
import { useMe } from "@/lib/use-me";

const ROLES = [
  { key: "chat", label: "Chat", hint: "answers, digests, agendas" },
  { key: "build", label: "Build", hint: "writes code, opens PRs" },
  { key: "review", label: "Review", hint: "judges PRs — must not share build's weights" },
] as const;

const PROVIDER_LABELS: Record<ProviderName, string> = {
  codex: "Codex", openrouter: "OpenRouter", bedrock: "Bedrock",
};

export default function ModelsPage() {
  const { data: me, isLoading: meLoading } = useMe();
  const { data: raw, isLoading, isError, error, refetch } = useModels();
  const setOverride = useSetModelOverride();
  // Optimistic per-role overrides so a provider/model switch shows up instantly instead
  // of waiting on the round trip + query invalidation. These are NOT reconciled against
  // fresh server data and NOT rolled back on mutation failure — a successful override
  // invalidates ["models"] and the next fetch re-renders from the server value, but until
  // then (or on error) the optimistic value stays. Acceptable for an admin-only,
  // single-tenant settings page; a failed override surfaces its own error toast.
  const [providerOverride, setProviderOverride] = useState<Partial<Record<string, ProviderName>>>({});
  const [modelOverride, setModelOverride] = useState<Partial<Record<string, string>>>({});

  if (meLoading) return <LoadingState rows={2} />;
  if (!me?.is_admin) return <NoAccessState />;

  // Distinguish the three states so we never spin a skeleton forever:
  // a genuine load, a 403 for non-admins, and any other failure.
  if (isLoading) {
    return <LoadingState rows={2} />;
  }
  if (isError) {
    if (isForbidden(error)) return <NoAccessState />;
    return <ErrorState onRetry={() => refetch()} message="Couldn't load models — try again." />;
  }
  // The backend always gives an admin caller the flat (non-`active`) shape;
  // guard defensively rather than asserting the type past the union.
  if (!raw || !isAdminModels(raw)) {
    return <ErrorState onRetry={() => refetch()} message="Couldn't load models — try again." />;
  }
  const data = raw;

  const codex = data.providers.find((p) => p.name === "codex");
  const openrouter = data.providers.find((p) => p.name === "openrouter");
  const bedrock = data.providers.find((p) => p.name === "bedrock");
  const codexConnected = codex?.usable ?? false;

  // Bedrock only shows up as a pickable provider once it's actually usable (AWS creds
  // present) — Codex and OpenRouter are always offered, each with their own connect/hint
  // state surfaced inline.
  const baseProviderOptions: ProviderName[] = ["codex", "openrouter", ...(bedrock?.usable ? (["bedrock"] as const) : [])];

  // A role's dropdown must always contain — and be able to display — that role's
  // currently-active provider, even if that provider has since lost its credentials
  // (e.g. Bedrock creds removed). Otherwise `value={provider}` has no matching <option>
  // and the browser silently coerces the select to its first entry ("Codex"), so the
  // dropdown would read "Codex" while the model area below shows Bedrock's "add creds"
  // hint — self-contradictory. Append the active provider (marked unavailable) when it's
  // not already offered so the select reflects the true state.
  const providerOptionsFor = (active: ProviderName): ProviderName[] =>
    baseProviderOptions.includes(active) ? baseProviderOptions : [...baseProviderOptions, active];

  const handleProviderChange = (roleKey: string, provider: ProviderName) => {
    setProviderOverride((prev) => ({ ...prev, [roleKey]: provider }));
    setOverride.mutate({ key: `model.provider.${roleKey}`, value: provider });
    // Never leave the model dropdown pointed at an id from the old provider's catalog —
    // default to the new provider's first model and persist it too, unless the new
    // provider has no catalog yet (no key configured).
    const catalog = data.catalogs[provider] ?? [];
    if (catalog.length > 0) {
      setModelOverride((prev) => ({ ...prev, [roleKey]: catalog[0] }));
      setOverride.mutate({ key: `model.${roleKey}`, value: catalog[0] });
    } else {
      setModelOverride((prev) => ({ ...prev, [roleKey]: "" }));
    }
  };

  const handleModelChange = (roleKey: string, model: string) => {
    setModelOverride((prev) => ({ ...prev, [roleKey]: model }));
    setOverride.mutate({ key: `model.${roleKey}`, value: model });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-lg tracking-tight">Models</h1>
        <p className="text-sm text-muted-foreground">
          Pick which provider and model handles each job
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {openrouter?.usable
            ? "OpenRouter connected ✓"
            : "OpenRouter: add OPENROUTER_API_KEY to .env to use it"}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Changes apply immediately to reports, builds, reviews, and App-Home asks. The
          always-on Slack chat assistant switches on Bott&apos;s next restart.
        </p>
      </div>

      <CodexConnect connected={codexConnected} />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {ROLES.map((role) => {
          const provider = providerOverride[role.key] ?? data.active.providers_by_role[role.key];
          const model = modelOverride[role.key] ?? data[role.key];
          const catalog = data.catalogs[provider] ?? [];
          const providerInfo = data.providers.find((p) => p.name === provider);
          const providerOptions = providerOptionsFor(provider);
          const isConflict = role.key === "review" && data.conflict;
          return (
            <div key={role.key} className={`rounded-xl border bg-card p-4 shadow-sm ${isConflict ? "border-amber-500/40" : ""}`}>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {role.label}
                {isConflict && <Badge variant="outline" className="text-amber-700 dark:text-amber-400">conflict</Badge>}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">{role.hint}</div>

              <label className="mt-3 block text-[10.5px] font-medium uppercase tracking-wide text-muted-foreground">
                Provider
              </label>
              <select
                aria-label={`${role.label} provider`}
                className="mt-1 w-full rounded-md border bg-background px-2.5 py-1.5 text-xs"
                value={provider}
                onChange={(e) => handleProviderChange(role.key, e.target.value as ProviderName)}
              >
                {providerOptions.map((p) => {
                  const unavailable = !baseProviderOptions.includes(p);
                  return (
                    <option key={p} value={p}>
                      {PROVIDER_LABELS[p]}{unavailable ? " (unavailable)" : ""}
                    </option>
                  );
                })}
              </select>

              <label className="mt-3 block text-[10.5px] font-medium uppercase tracking-wide text-muted-foreground">
                Model
              </label>
              {catalog.length > 0 ? (
                <select
                  aria-label={`${role.label} model`}
                  className="mt-1 w-full rounded-md border bg-background px-2.5 py-1.5 font-mono text-xs"
                  value={model}
                  onChange={(e) => handleModelChange(role.key, e.target.value)}
                >
                  {catalog.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              ) : (
                <div className="mt-1 text-xs text-muted-foreground">
                  {providerInfo?.hint ?? "Connect this provider above to pick a model."}
                </div>
              )}
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
