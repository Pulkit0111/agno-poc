"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { api } from "@/lib/api";
import { relativeTime } from "@/lib/time";
import type { Approval } from "@/lib/types";

function prettyPayload(payload?: string | null): string | null {
  if (!payload) return null;
  try {
    return JSON.stringify(JSON.parse(payload), null, 2);
  } catch {
    return payload;
  }
}

const GATE_REASON: Record<string, string> = {
  api: "Writes to shared systems wait for a human OK. Reads never gate.",
  build: "Code changes always get a human plan approval before Bott touches a repo.",
  triage: "Fixes proposed from error triage need a human OK before implementation.",
};

export function ApprovalDrawer({
  id,
  onClose,
  onDecide,
}: {
  id: number | null;
  onClose: () => void;
  onDecide: (id: number, approve: boolean) => void;
}) {
  const { data: row } = useQuery({
    queryKey: ["approval", id],
    queryFn: () => api<Approval>(`/api/console/v1/approvals/${id}`),
    enabled: id !== null,
  });
  const payload = prettyPayload(row?.payload);
  const family = row?.action.split(":")[0] ?? "api";

  return (
    <Sheet open={id !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-[400px] sm:max-w-[440px]">
        {row && (
          <>
            <SheetHeader>
              <SheetTitle className="text-base">{row.summary}</SheetTitle>
            </SheetHeader>
            <div className="space-y-4 px-4 text-sm">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="font-mono text-[11px]">{row.action}</Badge>
                <span className="text-xs text-muted-foreground">
                  {row.user_id} · {relativeTime(row.created)}
                </span>
              </div>
              {payload && (
                <pre className="max-h-64 overflow-auto rounded-lg border bg-muted p-3 font-mono text-xs leading-relaxed">
                  {payload}
                </pre>
              )}
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-muted-foreground">
                <span className="font-medium text-amber-700 dark:text-amber-400">Why this gated: </span>
                {GATE_REASON[family] ?? GATE_REASON.api}
              </div>
              {row.status === "pending" ? (
                <div className="flex gap-2">
                  <Button className="flex-1" onClick={() => { onDecide(row.id, true); onClose(); }}>
                    Approve &amp; run
                  </Button>
                  <Button variant="outline" className="flex-1" onClick={() => { onDecide(row.id, false); onClose(); }}>
                    Dismiss
                  </Button>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Already {row.status} by {row.decided_by}.
                </p>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
