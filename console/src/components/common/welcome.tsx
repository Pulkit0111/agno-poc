"use client";

import { useEffect, useState } from "react";
import { MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";

const STORAGE_KEY = "bott.welcome.seen";

/**
 * One-time, dismissible welcome modal shown on a user's first visit to the
 * console. Dismissal persists in localStorage. Renders nothing during SSR or
 * once dismissed.
 */
export function Welcome() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    // Read localStorage only after mount so server and first client render both
    // produce null (no hydration mismatch); the setState here is the intended
    // "sync from an external store on mount" case, not a cascading-render bug.
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (!localStorage.getItem(STORAGE_KEY)) setShow(true);
    } catch {
      // localStorage unavailable (private mode / SSR) — skip the welcome.
    }
  }, []);

  function dismiss() {
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      // ignore write failures
    }
    setShow(false);
  }

  if (!show) return null;

  return (
    <div
      className="fixed inset-0 z-[60] grid place-items-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="welcome-title"
    >
      <div className="w-full max-w-md rounded-xl border bg-card p-6 shadow-lg motion-reduce:transition-none">
        <div className="flex items-center gap-3">
          <div className="grid size-9 flex-none place-items-center rounded-lg bg-primary text-base font-bold text-primary-foreground">
            B
          </div>
          <h2 id="welcome-title" className="text-base font-semibold tracking-tight">
            Welcome to the Bott Console
          </h2>
        </div>
        <div className="mt-4 space-y-3 text-sm text-muted-foreground">
          <p>
            <span className="font-medium text-foreground">Bott</span> is your AI
            engineering teammate in Slack — it triages issues, runs skills, and
            ships fixes alongside the team.
          </p>
          <p>
            This console is your cockpit for the work behind those conversations:
            review <span className="font-medium text-foreground">approvals</span>,
            manage <span className="font-medium text-foreground">schedules</span>,
            and keep an eye on{" "}
            <span className="font-medium text-foreground">health</span> and{" "}
            <span className="font-medium text-foreground">activity</span>.
          </p>
          <p className="flex items-center gap-2 rounded-lg bg-muted/60 px-3 py-2 text-foreground">
            <MessageSquare className="size-4 flex-none text-muted-foreground" />
            Conversations with Bott still happen in Slack.
          </p>
        </div>
        <div className="mt-6 flex justify-end">
          <Button onClick={dismiss}>Got it</Button>
        </div>
      </div>
    </div>
  );
}
