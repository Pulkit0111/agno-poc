"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity, Building2, CalendarClock, ClipboardCheck, Grid2x2, Hand,
  HeartPulse, House, Library, ListChecks, LucideIcon, MessageSquareQuote,
  PanelLeftClose, PanelLeftOpen, Settings2, Shield, SquareTerminal, Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useMe } from "@/lib/use-me";
import { useApprovalCount } from "@/lib/use-approval-count";
import { Sheet, SheetContent } from "@/components/ui/sheet";

/** localStorage key for the desktop rail's collapsed/expanded state. */
const SIDEBAR_STORAGE_KEY = "console.sidebar";

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
  href, label, icon: Icon, trailing, onNavigate, collapsed,
}: NavItem & { trailing?: React.ReactNode; onNavigate?: () => void; collapsed?: boolean }) {
  const pathname = usePathname();
  const active = pathname === href;
  return (
    <Link
      href={href}
      onClick={onNavigate}
      title={label}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground",
        collapsed && "justify-center px-0",
        active && "bg-accent font-medium text-accent-foreground",
      )}
    >
      <Icon className="size-4 shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
      {!collapsed && trailing}
    </Link>
  );
}

export function SidebarNav({
  isAdmin, onNavigate, collapsed = false,
}: { isAdmin: boolean; onNavigate?: () => void; collapsed?: boolean }) {
  return (
    <nav className="flex flex-1 flex-col gap-0.5">
      {MEMBER.map((i) => (
        <Item
          key={i.href}
          {...i}
          onNavigate={onNavigate}
          collapsed={collapsed}
          trailing={isAdmin && i.href === "/approvals" ? <ApprovalBadge /> : undefined}
        />
      ))}
      {isAdmin && (
        <>
          {!collapsed && (
            <div className="px-2.5 pb-1 pt-4 text-[10.5px] font-semibold uppercase tracking-widest text-muted-foreground">
              Administration
            </div>
          )}
          {ADMIN.map((i) => <Item key={i.href} {...i} onNavigate={onNavigate} collapsed={collapsed} />)}
        </>
      )}
    </nav>
  );
}

/** Logo + nav + (optional) collapse toggle + footer — shared by the desktop rail and the mobile drawer. */
function SidebarInner({ isAdmin, email, onNavigate, collapsed = false, toggle }: {
  isAdmin: boolean; email?: string; onNavigate?: () => void; collapsed?: boolean; toggle?: React.ReactNode;
}) {
  return (
    <>
      <div className={cn("flex items-center gap-2.5 px-2 pb-3", collapsed && "justify-center px-0")}>
        {/* eslint-disable-next-line @next/next/no-img-element -- fixed local asset, no next/image benefit */}
        <img src="/logo.png" alt="" className="size-[30px] shrink-0 rounded-lg border border-border object-cover" />
        {!collapsed && (
          <div className="leading-tight">
            <div className="font-display text-[13.5px]">bott console</div>
            <div className="text-[11px] text-muted-foreground">Axelerant</div>
          </div>
        )}
      </div>
      <SidebarNav isAdmin={isAdmin} onNavigate={onNavigate} collapsed={collapsed} />
      {toggle}
      {!collapsed && (
        <div className="border-t pt-2 text-xs text-muted-foreground">
          <div className="truncate px-2 font-medium text-foreground">{email ?? "…"}</div>
          <div className="px-2">{isAdmin ? "Admin" : "Member"}</div>
        </div>
      )}
    </>
  );
}

export function Sidebar({
  open, onOpenChange,
}: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { data: me } = useMe();
  const isAdmin = me?.is_admin ?? false;
  const [collapsed, setCollapsed] = useState(false);

  // Read the persisted preference after mount only — reading localStorage
  // during render would diverge from the server-rendered (always-expanded)
  // markup and trip a hydration mismatch. A deliberate one-time sync to an
  // external system (localStorage), not a cascading-render bug — see the
  // matching pattern in (app)/layout.tsx.
  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCollapsed(window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "collapsed");
    } catch {
      // localStorage unavailable (private browsing, disabled storage, etc.) — stay expanded.
    }
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(SIDEBAR_STORAGE_KEY, next ? "collapsed" : "expanded");
      } catch {
        // Best-effort persistence only.
      }
      return next;
    });
  };

  return (
    <>
      {/* Desktop rail — fixed on md+ */}
      <aside
        className={cn(
          "hidden h-full flex-none flex-col gap-2 overflow-y-auto border-r bg-sidebar p-3 transition-[width] duration-150 md:flex",
          collapsed ? "w-[58px] items-center px-1.5" : "w-56",
        )}
      >
        <SidebarInner
          isAdmin={isAdmin}
          email={me?.email}
          collapsed={collapsed}
          toggle={
            <button
              type="button"
              onClick={toggleCollapsed}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className={cn(
                "mt-1 flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground",
                collapsed && "justify-center px-0",
              )}
            >
              {collapsed ? <PanelLeftOpen className="size-4 shrink-0" /> : <PanelLeftClose className="size-4 shrink-0" />}
              {!collapsed && <span>Collapse</span>}
            </button>
          }
        />
      </aside>

      {/* Mobile drawer — off-canvas; Sheet handles backdrop, Escape and focus trap.
          Always fully expanded: collapsing an off-canvas drawer serves no purpose. */}
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side="left"
          showCloseButton={false}
          className="flex w-64 flex-col gap-2 overflow-y-auto bg-sidebar p-3 motion-reduce:transition-none md:hidden"
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
