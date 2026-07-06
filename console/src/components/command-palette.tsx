"use client";

import { Command } from "cmdk";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";

const PAGES = [
  { label: "Home", href: "/" },
  { label: "Approvals", href: "/approvals" },
  { label: "Activity", href: "/activity" },
  { label: "Schedules", href: "/schedules" },
  { label: "Action items", href: "/action-items" },
  { label: "Skills", href: "/skills" },
  { label: "Reports", href: "/reports" },
  { label: "Connectors", href: "/connectors" },
  { label: "Admin · Models", href: "/admin/models" },
  { label: "Admin · Engagements", href: "/admin/engagements" },
  { label: "Admin · Policy", href: "/admin/policy" },
  { label: "Admin · Prompts", href: "/admin/prompts" },
  { label: "Admin · Users & roles", href: "/admin/users" },
  { label: "Admin · System", href: "/admin/system" },
];

const RUN_ACTIONS = [
  { label: "Run security check", kind: "security" },
  { label: "Run portfolio snapshot", kind: "portfolio" },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const router = useRouter();

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  async function runAction(kind: string) {
    setOpen(false);
    try {
      const res = await api<{ result: string }>("/api/console/v1/reports/run", {
        method: "POST", body: JSON.stringify({ kind }),
      });
      toast.success("Done", { description: res.result.slice(0, 140) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "That action failed.");
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/40" onClick={() => setOpen(false)}>
      <div className="mx-auto mt-24 w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <Command className="overflow-hidden rounded-xl border bg-popover shadow-lg">
          <Command.Input autoFocus placeholder="Search pages or run an action…" className="w-full border-b bg-transparent px-4 py-3 text-sm outline-none" />
          <Command.List className="max-h-80 overflow-y-auto p-2">
            <Command.Empty className="px-2 py-6 text-center text-sm text-muted-foreground">No matches.</Command.Empty>
            <Command.Group heading="Pages" className="text-xs font-medium text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
              {PAGES.map((p) => (
                <Command.Item
                  key={p.href}
                  onSelect={() => { setOpen(false); router.push(p.href); }}
                  className="cursor-pointer rounded-md px-2 py-2 text-sm data-[selected=true]:bg-accent"
                >
                  {p.label}
                </Command.Item>
              ))}
            </Command.Group>
            <Command.Group heading="Actions" className="text-xs font-medium text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
              {RUN_ACTIONS.map((a) => (
                <Command.Item
                  key={a.kind}
                  onSelect={() => runAction(a.kind)}
                  className="cursor-pointer rounded-md px-2 py-2 text-sm data-[selected=true]:bg-accent"
                >
                  {a.label}
                </Command.Item>
              ))}
            </Command.Group>
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
