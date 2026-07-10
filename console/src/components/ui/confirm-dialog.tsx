"use client";

import type { ReactNode } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

/**
 * Controlled confirm modal built on the same base-ui Dialog as Sheet.
 * Focus-trap and Escape-to-close come from base-ui.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  warning,
  confirmLabel,
  onConfirm,
  tone = "default",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  warning?: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  tone?: "default" | "danger";
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-black/10 transition-opacity duration-150 data-ending-style:opacity-0 data-starting-style:opacity-0 supports-backdrop-filter:backdrop-blur-xs" />
        <Dialog.Popup className="fixed top-1/2 left-1/2 z-50 flex w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-xl border bg-popover bg-clip-padding p-5 text-sm text-popover-foreground shadow-lg transition duration-200 data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0">
          <div className="flex flex-col gap-1.5">
            <Dialog.Title className="font-heading text-base font-medium text-foreground">
              {title}
            </Dialog.Title>
            {description && (
              <Dialog.Description className="text-sm text-muted-foreground">
                {description}
              </Dialog.Description>
            )}
          </div>
          {warning && (
            <div
              className={cn(
                "rounded-lg border px-3 py-2 text-xs",
                tone === "danger"
                  ? "border-red-600/30 bg-red-500/5 text-red-700 dark:text-red-400"
                  : "border-amber-600/30 bg-amber-500/5 text-amber-700 dark:text-amber-400"
              )}
            >
              <div className="flex gap-2">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
                <div>{warning}</div>
              </div>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Dialog.Close render={<Button variant="outline" size="sm" />}>
              Cancel
            </Dialog.Close>
            <Button
              variant={tone === "danger" ? "destructive" : "default"}
              size="sm"
              onClick={() => {
                onConfirm();
                onOpenChange(false);
              }}
            >
              {confirmLabel}
            </Button>
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
