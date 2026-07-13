"use client";

import { useState, type KeyboardEvent } from "react";
import { Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-pill";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { SnoozeMenu } from "@/components/action-items/snooze-menu";
import { dueLabel } from "@/lib/snooze";
import { relativeTime } from "@/lib/time";
import {
  useActionItems, useCompleteActionItem, useCreateActionItem, useSnoozeActionItem,
  type ActionItem, type ActionItemSource,
} from "@/lib/use-action-items";

const SOURCE_PHRASE: Record<ActionItemSource, string> = {
  user: "you asked Bott",
  dsm: "from Daily standup",
  console: "added here",
};

function ActionItemRow({ item }: { item: ActionItem }) {
  const complete = useCompleteActionItem();
  const snooze = useSnoozeActionItem();

  return (
    <div className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{item.text}</div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="truncate">
            {SOURCE_PHRASE[item.source] ?? "added here"} · captured {relativeTime(item.created)}
          </span>
          {item.status === "snoozed" && item.remind_at != null && (
            <StatusPill tone="warn" label={dueLabel(item.remind_at)} className="flex-none" />
          )}
        </div>
      </div>
      {item.status !== "done" && (
        <div className="flex flex-none items-center gap-1.5">
          <Button
            size="sm" variant="outline"
            className="border-green-600/30 text-green-700 hover:bg-green-600/10 dark:text-green-400"
            onClick={() => complete.mutate(item.id)}
          >
            Done
          </Button>
          <SnoozeMenu onSnooze={(remindAt) => snooze.mutate({ id: item.id, remindAt })} />
        </div>
      )}
    </div>
  );
}

export default function ActionItemsPage() {
  const [tab, setTab] = useState<"open" | "done">("open");
  const { data: items, isLoading, isError, refetch } = useActionItems(tab === "done");
  const create = useCreateActionItem();
  const [text, setText] = useState("");

  const visible = tab === "done" ? items?.filter((i) => i.status === "done") : items;
  const openCount = tab === "open" ? items?.length : undefined;

  function submitAdd() {
    const trimmed = text.trim();
    if (!trimmed) return;
    create.mutate(trimmed, { onSuccess: () => setText("") });
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") submitAdd();
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-lg tracking-tight">Action items</h1>
        <p className="text-sm text-muted-foreground">
          Yours to close — captured from standups, threads, or whenever you ask Bott to track something
        </p>
      </div>

      <div className="flex gap-2 rounded-xl border bg-muted/40 px-3 py-2.5 text-sm">
        <Info className="mt-0.5 size-4 flex-none text-muted-foreground" />
        <p className="text-muted-foreground">
          Also in Bott&apos;s App Home in Slack. Snoozed items come back as a{" "}
          <b className="font-medium text-foreground">DM reminder</b> when they&apos;re due.
        </p>
      </div>

      <div className="flex gap-1 border-b text-sm">
        <button
          type="button"
          onClick={() => setTab("open")}
          className={`border-b-2 px-3 py-1.5 ${tab === "open" ? "border-primary font-medium text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}
        >
          Open{openCount != null ? ` · ${openCount}` : ""}
        </button>
        <button
          type="button"
          onClick={() => setTab("done")}
          className={`border-b-2 px-3 py-1.5 ${tab === "done" ? "border-primary font-medium text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}
        >
          Done
        </button>
      </div>

      {tab === "open" && (
        <div className="flex gap-2">
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Add an action item… e.g. 'Send the SOW draft to Globex by Thursday'"
            aria-label="Add an action item"
            className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
          />
          <Button onClick={submitAdd} disabled={create.isPending || !text.trim()}>Add</Button>
        </div>
      )}

      <div className="rounded-xl border bg-card shadow-sm">
        {isLoading && <LoadingState />}
        {isError && <ErrorState message="Couldn't load — try refreshing the page." onRetry={() => refetch()} />}
        {!isLoading && !isError && !visible?.length && (
          <EmptyState
            title={tab === "done" ? "Nothing done yet" : "Nothing open"}
            message={tab === "done" ? "Items you complete will show up here." : "You're all caught up."}
          />
        )}
        {visible?.map((item) => <ActionItemRow key={item.id} item={item} />)}
      </div>
    </div>
  );
}
