import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { statusMeta, toneClass, type Tone } from "@/lib/status";

type StatusPillProps =
  | { status: string; tone?: never; label?: never; className?: string }
  | { tone: Tone; label: string; status?: never; className?: string };

/**
 * Renders a status/verdict as an outline pill using the shared palette in lib/status.
 * Pass a raw `status` (job status or verdict) OR an explicit `tone` + `label`.
 */
export function StatusPill(props: StatusPillProps) {
  const meta =
    "status" in props && props.status !== undefined
      ? statusMeta(props.status)
      : { tone: props.tone, label: props.label };
  return (
    <Badge variant="outline" className={cn(toneClass[meta.tone], props.className)}>
      {meta.label}
    </Badge>
  );
}
