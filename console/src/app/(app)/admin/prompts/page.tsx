"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/time";
import { usePrompt, useRevertPrompt, useSavePrompt } from "@/lib/use-prompts";

const PROMPTS = [
  { key: "identity", label: "Identity" },
  { key: "voice", label: "Voice" },
] as const;

export default function PromptsPage() {
  const [active, setActive] = useState<(typeof PROMPTS)[number]["key"]>("voice");
  const { data, isLoading } = usePrompt(active);
  const save = useSavePrompt(active);
  const revert = useRevertPrompt(active);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (data) setDraft(data.current);
    setNote("");
  }, [data, active]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Prompts</h1>
        <p className="text-sm text-muted-foreground">Bott&apos;s identity and voice — versioned, revertible, never lost</p>
      </div>
      <div className="flex gap-2">
        {PROMPTS.map((p) => (
          <button
            key={p.key}
            onClick={() => setActive(p.key)}
            className={`rounded-full border px-3 py-1.5 text-sm font-medium ${
              active === p.key ? "border-primary/40 bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border bg-card shadow-sm">
          <div className="border-b px-4 py-2.5 text-sm font-semibold">Editor</div>
          {isLoading ? <div className="p-4"><Skeleton className="h-48" /></div> : (
            <div className="space-y-3 p-4">
              <textarea
                className="h-64 w-full rounded-md border bg-background px-2.5 py-1.5 font-mono text-xs"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
              <input
                className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
                placeholder="What changed and why (required)"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              <Button
                disabled={!note || draft === data?.current || save.isPending}
                onClick={() => save.mutate({ content: draft, note }, { onSuccess: () => setNote("") })}
              >
                Save as new version
              </Button>
            </div>
          )}
        </div>

        <div className="rounded-xl border bg-card shadow-sm">
          <div className="border-b px-4 py-2.5 text-sm font-semibold">Version history</div>
          {isLoading ? <div className="p-4"><Skeleton className="h-48" /></div> : (
            <ul>
              {!data?.versions.length && (
                <li className="px-4 py-6 text-sm text-muted-foreground">No saved versions yet — using the built-in default.</li>
              )}
              {data?.versions.map((v) => (
                <li key={v.id} className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{v.note}</div>
                    <div className="text-xs text-muted-foreground">{v.author} · {relativeTime(v.created)}</div>
                  </div>
                  <Button size="sm" variant="ghost" onClick={() => revert.mutate(v.id)}>Revert to this</Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <p className="max-w-2xl text-xs text-muted-foreground">
        Saved versions apply immediately to Bott&apos;s per-conversation replies. The main chat
        connection picks up a new version the next time it restarts.
      </p>
    </div>
  );
}
