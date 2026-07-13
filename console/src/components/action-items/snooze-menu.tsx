"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { nextMondayMorning, pickedDateMorning, tomorrowMorning } from "@/lib/snooze";

/**
 * Small controlled popover (no dropdown/popover primitive exists yet in components/ui) —
 * closes on Escape or an outside click, per the mockup's `.snooze-menu`.
 */
export function SnoozeMenu({ onSnooze }: { onSnooze: (remindAt: number) => void }) {
  const [open, setOpen] = useState(false);
  const [pickingDate, setPickingDate] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") { setOpen(false); setPickingDate(false); }
    }
    function onPointerDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setPickingDate(false);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onPointerDown);
    };
  }, [open]);

  function pick(remindAt: number) {
    onSnooze(remindAt);
    setOpen(false);
    setPickingDate(false);
  }

  return (
    <div ref={rootRef} className="relative">
      <Button size="sm" variant="ghost" onClick={() => setOpen((o) => !o)}>
        Snooze ▾
      </Button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-1 min-w-[170px] rounded-lg border bg-popover p-1 text-sm shadow-lg">
          {!pickingDate ? (
            <>
              <button
                type="button"
                className="block w-full rounded-md px-2.5 py-1.5 text-left hover:bg-muted"
                onClick={() => pick(tomorrowMorning())}
              >
                Tomorrow morning
              </button>
              <button
                type="button"
                className="block w-full rounded-md px-2.5 py-1.5 text-left hover:bg-muted"
                onClick={() => pick(nextMondayMorning())}
              >
                Next week
              </button>
              <button
                type="button"
                className="block w-full rounded-md px-2.5 py-1.5 text-left hover:bg-muted"
                onClick={() => setPickingDate(true)}
              >
                Pick a date…
              </button>
            </>
          ) : (
            <div className="p-1">
              <input
                type="date"
                autoFocus
                aria-label="Pick a date"
                className="w-full rounded-md border bg-background px-2 py-1 text-sm"
                onChange={(e) => { if (e.target.value) pick(pickedDateMorning(e.target.value)); }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
