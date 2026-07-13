"use client";

import { Menu, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";

const NAMES: Record<string, string> = {
  "/": "Home", "/activity": "Activity",
  "/schedules": "Schedules", "/action-items": "Action items",
  "/todos": "Todos",
  "/skills": "Skills", "/connectors": "Connectors",
  "/admin/system": "System",
  "/admin/models": "Models", "/admin/engagements": "Engagements",
  "/admin/users": "Users", "/admin/policy": "Policy",
  "/admin/prompts": "Prompts",
};

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const { resolvedTheme, setTheme } = useTheme();
  const pathname = usePathname();
  return (
    <header className="flex items-center gap-3 border-b bg-card px-4 py-2.5 md:px-6">
      <Button
        variant="ghost"
        size="icon"
        aria-label="Open navigation"
        className="md:hidden"
        onClick={onMenu}
      >
        <Menu className="size-4" />
      </Button>
      <span className="font-display text-[15px]">{NAMES[pathname] ?? "Bott Console"}</span>
      <div className="ml-auto flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Toggle theme"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          <Sun className="size-4 dark:hidden" />
          <Moon className="hidden size-4 dark:block" />
        </Button>
        <form action="/api/console/auth/logout" method="post">
          <Button variant="ghost" size="sm" type="submit">Sign out</Button>
        </form>
      </div>
    </header>
  );
}
