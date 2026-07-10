"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-pill";
import { relativeTime } from "@/lib/time";
import type { Approval } from "@/lib/types";
import { useMe } from "@/lib/use-me";

export function ApprovalRow({
  approval,
  onDecide,
  onOpen,
}: {
  approval: Approval;
  onDecide: (id: number, approve: boolean) => void;
  onOpen?: (id: number) => void;
}) {
  const { data: me } = useMe();

  return (
    <div className="flex items-start gap-3 border-b px-4 py-3 last:border-b-0">
      <Badge variant="outline" className="mt-0.5 font-mono text-[11px]">
        {approval.action.split(":").slice(0, 2).join(":")}
      </Badge>
      <button
        type="button"
        onClick={() => onOpen?.(approval.id)}
        className="min-w-0 flex-1 text-left"
      >
        <div className="truncate text-sm font-medium">{approval.summary}</div>
        <div className="text-xs text-muted-foreground">
          requested {relativeTime(approval.created)}
        </div>
      </button>
      {me?.is_admin ? (
        <div className="flex flex-none gap-1.5">
          <Button size="sm" variant="outline"
            className="border-green-600/30 text-green-700 hover:bg-green-600/10 dark:text-green-400"
            onClick={() => onDecide(approval.id, true)}>
            Approve
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onDecide(approval.id, false)}>
            Dismiss
          </Button>
        </div>
      ) : (
        <StatusPill tone="accent" label="Awaiting admin" className="mt-0.5 flex-none" />
      )}
    </div>
  );
}
