"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity, Building2, CalendarClock, ClipboardCheck, Grid2x2, Hand,
  HeartPulse, House, Library, ListChecks, LucideIcon, MessageSquareQuote,
  Settings2, Shield, SquareTerminal, Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useMe } from "@/lib/use-me";
import { useApprovalCount } from "@/lib/use-approval-count";
import { Sheet, SheetContent } from "@/components/ui/sheet";

type NavItem = { href: string; label: string; icon: LucideIcon };

const MEMBER: NavItem[] = [
  { href: "/", label: "Home", icon: House },
  { href: "/approvals", label: "Approvals", icon: Hand },
  { href: "/schedules", label: "Schedules", icon: CalendarClock },
  { href: "/action-items", label: "Action items", icon: ListChecks },
  { href: "/skills", label: "Skills", icon: Library },
  { href: "/reports", label: "Reports", icon: Grid2x2 },
  { href: "/connectors", label: "Connectors", icon: SquareTerminal },
];

const ADMIN: NavItem[] = [
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/admin/health", label: "Health", icon: HeartPulse },
  { href: "/admin/reviews", label: "Reviews", icon: ClipboardCheck },
  { href: "/admin/models", label: "Models", icon: Settings2 },
  { href: "/admin/engagements", label: "Engagements", icon: Building2 },
  { href: "/admin/policy", label: "Policy", icon: Shield },
  { href: "/admin/prompts", label: "Prompts", icon: MessageSquareQuote },
  { href: "/admin/users", label: "Users", icon: Users },
];

/** Live pending-approvals pill; only mounted for admins so the endpoint never 403s a member. */
function ApprovalBadge() {
  const { data } = useApprovalCount();
  const pending = data?.pending ?? 0;
  if (pending <= 0) return null;
  return (
    <span className="ml-auto grid min-w-[1.25rem] place-items-center rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10.5px] font-semibold tabular-nums text-amber-600 dark:text-amber-400">
      {pending}
    </span>
  );
}

function Item({
  href, label, icon: Icon, trailing, onNavigate,
}: NavItem & { trailing?: React.ReactNode; onNavigate?: () => void }) {
  const pathname = usePathname();
  const active = pathname === href;
  return (
    <Link
      href={href}
      onClick={onNavigate}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground",
        active && "bg-primary/10 font-medium text-primary",
      )}
    >
      <Icon className="size-4" /> {label}
      {trailing}
    </Link>
  );
}

export function SidebarNav({
  isAdmin, onNavigate,
}: { isAdmin: boolean; onNavigate?: () => void }) {
  return (
    <nav className="flex flex-1 flex-col gap-0.5">
      {MEMBER.map((i) => (
        <Item
          key={i.href}
          {...i}
          onNavigate={onNavigate}
          trailing={isAdmin && i.href === "/approvals" ? <ApprovalBadge /> : undefined}
        />
      ))}
      {isAdmin && (
        <>
          <div className="px-2.5 pb-1 pt-4 text-[10.5px] font-semibold uppercase tracking-widest text-muted-foreground">
            Administration
          </div>
          {ADMIN.map((i) => <Item key={i.href} {...i} onNavigate={onNavigate} />)}
        </>
      )}
    </nav>
  );
}

/** Logo + nav + footer — shared by the desktop rail and the mobile drawer. */
function SidebarInner({ isAdmin, email, onNavigate }: {
  isAdmin: boolean; email?: string; onNavigate?: () => void;
}) {
  return (
    <>
      <div className="flex items-center gap-2.5 px-2 pb-3">
        <div className="grid size-7 place-items-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">B</div>
        <div className="leading-tight">
          <div className="text-sm font-semibold">Bott Console</div>
          <div className="text-[10px] text-muted-foreground">Axelerant</div>
        </div>
      </div>
      <SidebarNav isAdmin={isAdmin} onNavigate={onNavigate} />
      <div className="border-t pt-2 text-xs text-muted-foreground">
        <div className="truncate px-2 font-medium text-foreground">{email ?? "…"}</div>
        <div className="px-2">{isAdmin ? "Admin" : "Member"}</div>
      </div>
    </>
  );
}

export function Sidebar({
  open, onOpenChange,
}: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { data: me } = useMe();
  const isAdmin = me?.is_admin ?? false;

  return (
    <>
      {/* Desktop rail — fixed on md+ */}
      <aside className="hidden h-full w-56 flex-none flex-col gap-2 overflow-y-auto border-r bg-card p-3 md:flex">
        <SidebarInner isAdmin={isAdmin} email={me?.email} />
      </aside>

      {/* Mobile drawer — off-canvas; Sheet handles backdrop, Escape and focus trap */}
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side="left"
          showCloseButton={false}
          className="flex w-64 flex-col gap-2 overflow-y-auto bg-card p-3 motion-reduce:transition-none md:hidden"
        >
          <SidebarInner
            isAdmin={isAdmin}
            email={me?.email}
            onNavigate={() => onOpenChange(false)}
          />
        </SheetContent>
      </Sheet>
    </>
  );
}
