"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { CategoryBadge } from "@/components/ui/category-badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { relativeTime } from "@/lib/time";
import type { ConsoleUser, Role } from "@/lib/use-users";
import { useInvite, useRevokeInvite, useSetRole, useUsers } from "@/lib/use-users";

function UserMeta({ user }: { user: ConsoleUser }) {
  if (user.invited) return <span>Invited · hasn&apos;t signed in yet</span>;
  if (user.last_active == null) return <span>Never active</span>;
  return <span>Last active {relativeTime(user.last_active)}</span>;
}

function UserAction({ user }: { user: ConsoleUser }) {
  const setRole = useSetRole();
  const revoke = useRevokeInvite();

  if (user.invited) {
    return (
      <Button
        size="sm"
        variant="destructive"
        disabled={revoke.isPending}
        onClick={() => revoke.mutate(user.email)}
      >
        Revoke
      </Button>
    );
  }
  if (user.locked) {
    return (
      <Button size="sm" variant="outline" disabled title="Server-seeded admins can't be demoted here — lockout protection">
        Locked
      </Button>
    );
  }
  if (user.role === "admin") {
    return (
      <Button
        size="sm"
        variant="destructive"
        disabled={setRole.isPending}
        onClick={() => setRole.mutate({ email: user.email, role: "member" })}
      >
        Remove admin
      </Button>
    );
  }
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={setRole.isPending}
      onClick={() => setRole.mutate({ email: user.email, role: "admin" })}
    >
      Make admin
    </Button>
  );
}

function InviteDrawer({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const invite = useInvite();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");

  function close() {
    onOpenChange(false);
    setEmail("");
    setRole("member");
  }

  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) close(); }}>
      <SheetContent className="w-[400px] sm:max-w-[440px]">
        <SheetHeader>
          <SheetTitle className="text-base">Invite user</SheetTitle>
        </SheetHeader>
        <div className="space-y-4 px-4 text-sm">
          <p className="text-xs text-muted-foreground">
            They&apos;ll sign in with Slack — this just sets their role ahead of time.
          </p>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Work email</label>
            <input
              className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
              placeholder="name@axelerant.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Role</label>
            <select
              className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
            >
              <option value="member">Member — use Bott, manage their own things</option>
              <option value="admin">Admin — decide approvals, operate the platform</option>
            </select>
          </div>
        </div>
        <SheetFooter className="flex-row justify-end">
          <Button variant="outline" onClick={close}>Cancel</Button>
          <Button
            disabled={!email.trim() || invite.isPending}
            onClick={() => invite.mutate({ email: email.trim(), role }, { onSuccess: close })}
          >
            Send invite
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

export default function UsersPage() {
  const { data: users, isLoading, isError, refetch } = useUsers();
  const [inviteOpen, setInviteOpen] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-lg tracking-tight">Users</h1>
          <p className="text-sm text-muted-foreground">
            Everyone Bott knows. Invite people ahead of their first sign-in, and manage who can decide for Bott.
          </p>
        </div>
        <Button onClick={() => setInviteOpen(true)}>Invite user</Button>
      </div>
      <div className="rounded-xl border bg-card shadow-sm">
        {isLoading && <LoadingState rows={2} />}
        {isError && <ErrorState onRetry={() => refetch()} message="Couldn't load users — try again." />}
        {!isLoading && !isError && !users?.length && (
          <EmptyState title="Nobody yet" message="Bott hasn't met anyone here yet." />
        )}
        {!isLoading && !isError && users?.map((u) => (
          <div key={u.email} className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{u.email}</div>
              <div className="text-xs text-muted-foreground"><UserMeta user={u} /></div>
            </div>
            <CategoryBadge kind={u.invited ? "invited" : u.role} />
            <UserAction user={u} />
          </div>
        ))}
      </div>
      <p className="max-w-lg text-xs text-muted-foreground">
        Anyone with an @axelerant.com Slack account can sign in as a member. Admins decide
        approvals, manage schedules for everyone, and operate the platform.
      </p>
      <InviteDrawer open={inviteOpen} onOpenChange={setInviteOpen} />
    </div>
  );
}
