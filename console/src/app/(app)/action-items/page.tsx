"use client";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/time";
import { useActionItems, useCompleteActionItem, useSnoozeActionItem } from "@/lib/use-action-items";

export default function ActionItemsPage() {
  const { data: items, isLoading, isError } = useActionItems(false);
  const complete = useCompleteActionItem();
  const snooze = useSnoozeActionItem();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Action items</h1>
        <p className="text-sm text-muted-foreground">Captured from standups and threads — yours to close</p>
      </div>
      <div className="rounded-xl border bg-card shadow-sm">
        {isLoading && <div className="space-y-2 p-4"><Skeleton className="h-9" /><Skeleton className="h-9" /></div>}
        {isError && (
          <div className="px-4 py-8 text-center text-sm text-destructive">
            Couldn't load — try refreshing the page.
          </div>
        )}
        {!isLoading && !isError && !items?.length && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">Nothing open — you&apos;re all caught up.</div>
        )}
        {items?.map((item) => (
          <div key={item.id} className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{item.text}</div>
              <div className="text-xs text-muted-foreground">captured {relativeTime(item.created)}</div>
            </div>
            <div className="flex flex-none gap-1.5">
              <Button size="sm" variant="outline"
                className="border-green-600/30 text-green-700 hover:bg-green-600/10 dark:text-green-400"
                onClick={() => complete.mutate(item.id)}>
                Done
              </Button>
              <Button size="sm" variant="ghost" onClick={() => snooze.mutate({ id: item.id })}>Snooze</Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
