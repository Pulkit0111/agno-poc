"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";

const NAMES: Record<string, string> = {
  "/": "Home", "/approvals": "Approvals", "/activity": "Activity",
};

export function Topbar() {
  const { resolvedTheme, setTheme } = useTheme();
  const pathname = usePathname();
  return (
    <header className="flex items-center gap-3 border-b bg-card px-6 py-2.5">
      <span className="text-sm font-medium">{NAMES[pathname] ?? "Bott Console"}</span>
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
