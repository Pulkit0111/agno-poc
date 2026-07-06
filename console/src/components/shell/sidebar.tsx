"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity, Building2, CalendarClock, Check, Grid2x2, Hand, House, Library,
  ListChecks, LucideIcon, MessageSquareQuote, Settings2, Shield, SquareTerminal, Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useMe } from "@/lib/use-me";

type NavItem = { href: string; label: string; icon: LucideIcon; soon?: boolean };

const MEMBER: NavItem[] = [
  { href: "/", label: "Home", icon: House },
  { href: "/approvals", label: "Approvals", icon: Hand },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/schedules", label: "Schedules", icon: CalendarClock },
  { href: "/action-items", label: "Action items", icon: ListChecks },
  { href: "/skills", label: "Skills", icon: Library },
  { href: "/reports", label: "Reports", icon: Grid2x2 },
  { href: "/connectors", label: "Connectors", icon: SquareTerminal },
];

const ADMIN: NavItem[] = [
  { href: "/admin/models", label: "Models", icon: Settings2 },
  { href: "/admin/engagements", label: "Engagements", icon: Building2 },
  { href: "/admin/policy", label: "Policy", icon: Shield },
  { href: "/admin/prompts", label: "Prompts", icon: MessageSquareQuote },
  { href: "/admin/users", label: "Users & roles", icon: Users },
  { href: "/admin/system", label: "System", icon: Check },
];

function Item({ href, label, icon: Icon, soon }: NavItem) {
  const pathname = usePathname();
  const active = pathname === href;
  if (soon) {
    return (
      <span className="flex cursor-default items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground/50">
        <Icon className="size-4" /> {label}
        <span className="ml-auto text-[10px] uppercase tracking-wide">soon</span>
      </span>
    );
  }
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground",
        active && "bg-primary/10 font-medium text-primary",
      )}
    >
      <Icon className="size-4" /> {label}
    </Link>
  );
}

export function SidebarNav({ isAdmin }: { isAdmin: boolean }) {
  return (
    <nav className="flex flex-1 flex-col gap-0.5">
      {MEMBER.map((i) => <Item key={i.href} {...i} />)}
      {isAdmin && (
        <>
          <div className="px-2.5 pb-1 pt-4 text-[10.5px] font-semibold uppercase tracking-widest text-muted-foreground">
            Administration
          </div>
          {ADMIN.map((i) => <Item key={i.href} {...i} />)}
        </>
      )}
    </nav>
  );
}

export function Sidebar() {
  const { data: me } = useMe();
  return (
    <aside className="flex h-full w-56 flex-none flex-col gap-2 overflow-y-auto border-r bg-card p-3">
      <div className="flex items-center gap-2.5 px-2 pb-3">
        <div className="grid size-7 place-items-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">B</div>
        <div className="leading-tight">
          <div className="text-sm font-semibold">Bott Console</div>
          <div className="text-[10px] text-muted-foreground">Axelerant</div>
        </div>
      </div>
      <SidebarNav isAdmin={me?.is_admin ?? false} />
      <div className="border-t pt-2 text-xs text-muted-foreground">
        <div className="truncate px-2 font-medium text-foreground">{me?.email ?? "…"}</div>
        <div className="px-2">{me?.is_admin ? "Admin" : "Member"}</div>
      </div>
    </aside>
  );
}
