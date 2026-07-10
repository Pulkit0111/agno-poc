"use client";

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ErrorState, LoadingState } from "@/components/common/states";
import { api, isForbidden } from "@/lib/api";
import { StatusPill } from "@/components/ui/status-pill";
import { Time } from "@/lib/time";
import type { Approval } from "@/lib/types";
import { useMe } from "@/lib/use-me";

/** A friendly, human title for an approval action like "api:jira" or "build:implement". */
function actionTitle(action: string): string {
  const [family, sub] = action.split(":");
  if (family === "build") return "Approve a code change";
  if (family === "triage") return "Approve a fix from error triage";
  if (family === "api") {
    const map: Record<string, string> = {
      jira: "Post a comment to Jira",
      github: "Write a change to GitHub",
      slack: "Post a message to Slack",
      gmail: "Send an email",
      calendar: "Change a calendar event",
      drive: "Write to Google Drive",
    };
    return map[sub] ?? `Write to ${sub ?? "a connected system"}`;
  }
  return action;
}

const GATE_REASON: Record<string, string> = {
  api: "Writes to shared systems wait for a human OK. Reads never gate.",
  build: "Code changes always get a human plan approval before Bott touches a repo.",
  triage: "Fixes proposed from error triage need a human OK before implementation.",
};

type Payload = Record<string, unknown>;

function parsePayload(payload?: string | null): Payload | null {
  if (!payload) return null;
  try {
    const parsed = JSON.parse(payload);
    return parsed && typeof parsed === "object" ? (parsed as Payload) : null;
  } catch {
    return null;
  }
}

function rawPayload(payload?: string | null): string | null {
  if (!payload) return null;
  try {
    return JSON.stringify(JSON.parse(payload), null, 2);
  } catch {
    return payload;
  }
}

/** Render a scalar payload value; skip objects/arrays (those go in raw). */
function scalar(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return null;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-2 text-sm">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export function ApprovalDrawer({
  id,
  onClose,
  onDecide,
}: {
  id: number | null;
  onClose: () => void;
  onDecide: (id: number, approve: boolean) => void;
}) {
  const { data: me } = useMe();
  const query = useQuery({
    queryKey: ["approval", id],
    queryFn: () => api<Approval>(`/api/console/v1/approvals/${id}`),
    enabled: id !== null,
  });
  const row = query.data;

  const payload = parsePayload(row?.payload);
  const raw = rawPayload(row?.payload);
  const family = row?.action.split(":")[0] ?? "api";

  // Known structured fields worth surfacing above the raw dump.
  const repo = payload ? scalar(payload.repo) ?? scalar(payload.repository) : null;
  const ref =
    payload
      ? scalar(payload.ref) ?? scalar(payload.ticket) ?? scalar(payload.issue) ?? scalar(payload.branch)
      : null;
  const plan = payload ? scalar(payload.plan) : null;
  const steps = payload && Array.isArray(payload.steps) ? (payload.steps as unknown[]) : null;

  return (
    <Sheet open={id !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-[400px] sm:max-w-[440px]">
        {query.isLoading && <LoadingState rows={4} />}

        {query.isError && (
          isForbidden(query.error) ? (
            <div className="px-4 py-10 text-center text-sm text-muted-foreground">
              You don&apos;t have access to this request.
            </div>
          ) : (
            <ErrorState onRetry={() => query.refetch()} message="Couldn't load this request." />
          )
        )}

        {row && (
          <>
            <SheetHeader>
              <SheetTitle className="text-base">{actionTitle(row.action)}</SheetTitle>
            </SheetHeader>
            <div className="space-y-4 px-4 text-sm">
              <p className="text-sm text-muted-foreground">{row.summary}</p>

              <dl className="space-y-2 rounded-lg border bg-muted/40 p-3">
                <Field label="Action">
                  <Badge variant="outline" className="font-mono text-[11px]">{row.action}</Badge>
                </Field>
                {repo && <Field label="Repo">{repo}</Field>}
                {ref && <Field label="Reference">{ref}</Field>}
                <Field label="Requested by">{row.user_id}</Field>
                <Field label="Requested">
                  <Time value={row.created} className="text-muted-foreground" />
                </Field>
              </dl>

              {plan && (
                <div className="rounded-lg border bg-card p-3">
                  <div className="mb-1 text-xs font-medium text-muted-foreground">Plan</div>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">{plan}</p>
                </div>
              )}

              {steps && steps.length > 0 && (
                <div className="rounded-lg border bg-card p-3">
                  <div className="mb-1 text-xs font-medium text-muted-foreground">Steps</div>
                  <ol className="list-decimal space-y-1 pl-5 text-sm">
                    {steps.map((s, i) => (
                      <li key={i}>{scalar(s) ?? JSON.stringify(s)}</li>
                    ))}
                  </ol>
                </div>
              )}

              {raw && (
                <details className="rounded-lg border">
                  <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground">
                    Show raw request
                  </summary>
                  <pre className="max-h-64 overflow-auto border-t bg-muted p-3 font-mono text-xs leading-relaxed">
                    {raw}
                  </pre>
                </details>
              )}

              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-muted-foreground">
                <span className="font-medium text-amber-700 dark:text-amber-400">Why this gated: </span>
                {GATE_REASON[family] ?? GATE_REASON.api}
              </div>

              {row.status && row.status !== "pending" ? (
                <p className="text-xs text-muted-foreground">
                  Already {row.status}{row.decided_by ? ` by ${row.decided_by}` : ""}.
                </p>
              ) : me?.is_admin ? (
                <div className="flex gap-2">
                  <Button className="flex-1" onClick={() => { onDecide(row.id, true); onClose(); }}>
                    Approve &amp; run
                  </Button>
                  <Button variant="outline" className="flex-1" onClick={() => { onDecide(row.id, false); onClose(); }}>
                    Dismiss
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <StatusPill tone="accent" label="Awaiting admin" />
                  <span>Bott will act as soon as an admin approves.</span>
                </div>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
