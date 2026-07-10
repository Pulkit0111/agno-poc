"use client";

import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { relativeTime } from "@/lib/time";
import { useUsers } from "@/lib/use-users";

export default function UsersPage() {
  const { data: users, isLoading, isError, refetch } = useUsers();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Users</h1>
        <p className="text-sm text-muted-foreground">Everyone Bott has met, and who can administer it</p>
      </div>
      <div className="rounded-xl border bg-card shadow-sm">
        {isLoading && <LoadingState rows={2} />}
        {isError && <ErrorState onRetry={() => refetch()} message="Couldn't load users — try again." />}
        {!isLoading && !isError && !users?.length && (
          <EmptyState title="Nobody yet" message="Bott hasn't met anyone here yet." />
        )}
        {!isLoading && !isError && users?.map((u) => (
          <div key={u.user_id} className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
            <div className="min-w-0 flex-1 truncate text-sm font-medium">{u.user_id}</div>
            <Badge variant="outline" className={u.is_admin ? "text-primary" : "text-muted-foreground"}>
              {u.is_admin ? "Admin" : "Member"}
            </Badge>
            <div className="w-24 flex-none text-right text-xs text-muted-foreground">{relativeTime(u.last_active)}</div>
          </div>
        ))}
      </div>
      <p className="max-w-lg text-xs text-muted-foreground">
        Roles are managed via the BOTT_ADMINS setting.
      </p>
    </div>
  );
}
