"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useEngagements, useMapEngagement, useUnmapEngagement } from "@/lib/use-engagements";

export default function EngagementsPage() {
  const { data: engagements, isLoading, isError } = useEngagements();
  const map = useMapEngagement();
  const unmap = useUnmapEngagement();
  const [channelId, setChannelId] = useState("");
  const [engagement, setEngagement] = useState("");

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Engagements</h1>
        <p className="text-sm text-muted-foreground">Channel ↔ engagement wiring — how Bott knows where it is</p>
      </div>

      <div className="rounded-xl border bg-card shadow-sm">
        {isLoading && <div className="space-y-2 p-4"><Skeleton className="h-9" /><Skeleton className="h-9" /></div>}
        {isError && <div className="px-4 py-8 text-center text-sm text-destructive">Couldn't load — try refreshing the page.</div>}
        {!isLoading && !isError && !engagements?.length && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">No channels mapped yet.</div>
        )}
        {engagements?.map((e) => (
          <div key={e.channel_id} className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{e.engagement}</div>
              <div className="text-xs text-muted-foreground">{e.channel_id} · {e.schedule_count} schedule{e.schedule_count === 1 ? "" : "s"}</div>
            </div>
            <Button size="sm" variant="ghost" onClick={() => unmap.mutate(e.channel_id)}>Unmap</Button>
          </div>
        ))}
      </div>

      <div className="max-w-md space-y-3 rounded-xl border bg-card p-4 shadow-sm">
        <div className="text-sm font-semibold">Map a channel</div>
        <input className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" placeholder="Channel ID (e.g. C0ATHDGRD1C)" value={channelId} onChange={(e) => setChannelId(e.target.value)} />
        <input className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm" placeholder="Engagement (e.g. acme-commerce)" value={engagement} onChange={(e) => setEngagement(e.target.value)} />
        <Button disabled={!channelId || !engagement || map.isPending} onClick={() => map.mutate({ channel_id: channelId, engagement })}>
          Map
        </Button>
      </div>
    </div>
  );
}
