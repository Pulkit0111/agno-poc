"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/time";
import { useUsers } from "@/lib/use-users";

export default function UsersPage() {
  const { data: users, isLoading, isError } = useUsers();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Users &amp; roles</h1>
        <p className="text-sm text-muted-foreground">Everyone Bott has met, and who can administer it</p>
      </div>
      <div className="rounded-xl border bg-card shadow-sm">
        {isLoading && <div className="space-y-2 p-4"><Skeleton className="h-9" /><Skeleton className="h-9" /></div>}
        {isError && <div className="px-4 py-8 text-center text-sm text-destructive">Couldn't load — try refreshing the page.</div>}
        {!isLoading && !isError && !users?.length && (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">Nobody yet.</div>
        )}
        {users?.map((u) => (
          <div key={u.user_id} className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
            <div className="min-w-0 flex-1 truncate text-sm font-medium">{u.user_id}</div>
            <Badge variant="outline" className={u.is_admin ? "text-primary" : "text-muted-foreground"}>
              {u.is_admin ? "Admin · env-seeded" : "Member"}
            </Badge>
            <div className="w-24 flex-none text-right text-xs text-muted-foreground">{relativeTime(u.last_active)}</div>
          </div>
        ))}
      </div>
      <p className="max-w-lg text-xs text-muted-foreground">
        Roles are set via the BOTT_ADMINS environment variable today — promote/demote from here is coming in a later update.
      </p>
    </div>
  );
}
