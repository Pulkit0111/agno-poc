import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

// One tag system, part 2: `category` = a soft badge with a fixed label per
// kind. Pair with KindChip (mono chip) and StatusPill (pill + dot) — do not
// restyle this per page.
const categoryBadgeVariants = cva(
  "inline-flex items-center whitespace-nowrap rounded-[5px] px-2 py-0.5 text-[10.5px] font-semibold tracking-wide",
  {
    variants: {
      kind: {
        builtin: "border border-input bg-secondary text-secondary-foreground",
        authored: "bg-accent text-accent-foreground",
        pinned: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
        admin: "bg-accent text-accent-foreground",
        member: "border border-input bg-secondary text-secondary-foreground",
        personal: "bg-accent text-accent-foreground",
        invited: "border border-input bg-secondary text-secondary-foreground",
      },
    },
  },
);

const LABEL = {
  builtin: "Built-in",
  authored: "Authored",
  pinned: "Pinned",
  admin: "Admin",
  member: "Member",
  personal: "Personal",
  invited: "Invited",
} as const;

export type CategoryKind = keyof typeof LABEL;

export function CategoryBadge({
  kind,
  className,
}: { className?: string } & VariantProps<typeof categoryBadgeVariants> & { kind: CategoryKind }) {
  return (
    <span className={cn(categoryBadgeVariants({ kind }), className)}>
      {LABEL[kind]}
    </span>
  );
}
