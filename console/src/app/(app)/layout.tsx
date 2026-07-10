"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { CommandPalette } from "@/components/command-palette";
import { Sidebar } from "@/components/shell/sidebar";
import { Topbar } from "@/components/shell/topbar";
import { Welcome } from "@/components/common/welcome";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const pathname = usePathname();

  // Close the mobile drawer whenever the route changes — a deliberate sync to an
  // external event (navigation), not a cascading-render bug.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDrawerOpen(false);
  }, [pathname]);

  return (
    <div className="flex h-screen overflow-hidden">
      <CommandPalette />
      <Welcome />
      <Sidebar open={drawerOpen} onOpenChange={setDrawerOpen} />
      <div className="flex h-full min-w-0 flex-1 flex-col">
        <Topbar onMenu={() => setDrawerOpen(true)} />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-5xl p-6">{children}</div>
        </main>
      </div>
    </div>
  );
}
