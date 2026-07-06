"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useConnectors } from "@/lib/use-connectors";
import { useMe } from "@/lib/use-me";

export default function ConnectorsPage() {
  const { data: me } = useMe();
  const { data: connectors, isLoading } = useConnectors();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Connectors</h1>
        <p className="text-sm text-muted-foreground">What Bott can reach on your behalf</p>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {isLoading && <><Skeleton className="h-20" /><Skeleton className="h-20" /></>}
        {connectors?.map((c) => (
          <div key={c.name} className="rounded-xl border bg-card p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold">{c.name}</span>
              <Badge variant="outline" className={c.ok ? "ml-auto text-green-700 dark:text-green-400" : "ml-auto text-destructive"}>
                {c.ok ? "Connected" : "Unavailable"}
              </Badge>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              {c.ok ? c.on : (me?.is_admin ? c.off : "Ask an admin to reconnect this.")}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
