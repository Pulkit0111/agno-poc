"use client";

import { Command } from "cmdk";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/use-me";

type Page = { label: string; href: string; admin?: boolean };

const PAGES: Page[] = [
  { label: "Home", href: "/" },
  { label: "Activity", href: "/activity" },
  { label: "Schedules", href: "/schedules" },
  { label: "Action items", href: "/action-items" },
  { label: "Todos", href: "/todos" },
  { label: "Skills", href: "/skills" },
  { label: "Connectors", href: "/connectors" },
  { label: "Admin · System", href: "/admin/system", admin: true },
  { label: "Admin · Models", href: "/admin/models", admin: true },
  { label: "Admin · Engagements", href: "/admin/engagements", admin: true },
  { label: "Admin · Policy", href: "/admin/policy", admin: true },
  { label: "Admin · Prompts", href: "/admin/prompts", admin: true },
  { label: "Admin · Users", href: "/admin/users", admin: true },
];

// Both run actions are admin-only (they hit admin report endpoints).
const RUN_ACTIONS = [
  { label: "Run security check", kind: "security" },
  { label: "Run portfolio snapshot", kind: "portfolio" },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const { data: me } = useMe();
  const isAdmin = me?.is_admin ?? false;

  const pages = PAGES.filter((p) => isAdmin || !p.admin);

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
              {pages.map((p) => (
                <Command.Item
                  key={p.href}
                  onSelect={() => { setOpen(false); router.push(p.href); }}
                  className="cursor-pointer rounded-md px-2 py-2 text-sm data-[selected=true]:bg-accent"
                >
                  {p.label}
                </Command.Item>
              ))}
            </Command.Group>
            {isAdmin && (
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
            )}
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
