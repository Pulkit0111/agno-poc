import { cn } from "@/lib/utils";

/**
 * One tag system, part 1: `kind` = a mono neutral chip for machine-ish
 * identifiers (job kinds, connector actions — e.g. `api:jira`). Pair with
 * CategoryBadge (soft badge) and StatusPill (pill + dot) — do not invent a
 * fourth tag style per page.
 */
export function KindChip({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-[5px] border border-input bg-secondary px-1.5 py-0.5 font-mono text-[10.5px] text-muted-foreground",
        className,
      )}
    >
      {children}
    </span>
  );
}
