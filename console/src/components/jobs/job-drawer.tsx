"use client";

import { ErrorState, LoadingState } from "@/components/common/states";
import { StatusPill } from "@/components/ui/status-pill";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Time } from "@/lib/time";
import { useJob } from "@/lib/use-jobs";

function pretty(s?: string): string {
  if (!s) return "";
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return s;
  }
}

export function JobDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { data: job, isLoading, isError, refetch } = useJob(id);
  return (
    <Sheet open={id !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-[400px] sm:max-w-[440px]">
        <SheetHeader>
          <SheetTitle className="text-base">
            {job ? (
              <>
                {job.kind} <span className="font-mono text-xs text-muted-foreground">#{job.id}</span>
              </>
            ) : (
              "Run detail"
            )}
          </SheetTitle>
        </SheetHeader>
        {isLoading && <LoadingState rows={4} />}
        {isError && <ErrorState message="Couldn't load this run." onRetry={() => refetch()} />}
        {job && (
          <div className="space-y-4 px-4 text-sm">
            <div className="flex items-center gap-2">
              <StatusPill status={job.status} />
              <span className="text-xs text-muted-foreground">
                {job.user_id ? `${job.user_id} · ` : ""}
                <Time value={job.created} />
                {(job.attempts ?? 0) > 1 && ` · ${job.attempts} attempts`}
              </span>
            </div>
            {job.args && (
              <div>
                <div className="mb-1 text-xs font-medium text-muted-foreground">Inputs</div>
                <pre className="max-h-56 overflow-auto rounded-lg border bg-muted p-3 font-mono text-xs leading-relaxed">
                  {pretty(job.args)}
                </pre>
              </div>
            )}
            {job.error && (
              <div>
                <div className="mb-1 text-xs font-medium text-red-700 dark:text-red-400">What went wrong</div>
                <pre className="max-h-40 overflow-auto rounded-lg border border-red-600/30 bg-red-500/5 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
                  {job.error}
                </pre>
              </div>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
