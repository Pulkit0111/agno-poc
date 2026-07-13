"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { buttonVariants } from "@/components/ui/button";
import { CategoryBadge } from "@/components/ui/category-badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { useSkills } from "@/lib/use-skills";

type Filter = "all" | "built_in" | "authored";

const FILTER_LABEL: Record<Filter, string> = { all: "All", built_in: "Built-in", authored: "Authored" };

export default function SkillsPage() {
  const { data: skills, isLoading, isError, refetch } = useSkills();
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  const counts = useMemo(
    () => ({
      all: skills?.length ?? 0,
      built_in: skills?.filter((s) => s.built_in).length ?? 0,
      authored: skills?.filter((s) => !s.built_in).length ?? 0,
    }),
    [skills],
  );

  const visible = useMemo(() => {
    if (!skills) return skills;
    const q = query.trim().toLowerCase();
    return skills.filter((s) => {
      if (filter === "built_in" && !s.built_in) return false;
      if (filter === "authored" && s.built_in) return false;
      if (!q) return true;
      return s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q);
    });
  }, [skills, filter, query]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-lg tracking-tight">Skills</h1>
        <p className="text-sm text-muted-foreground">
          What Bott has learned to do. Open any skill to read it; authored skills can be edited.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search skills…"
          aria-label="Search skills"
          className="w-full max-w-[260px] rounded-md border bg-background px-2.5 py-1.5 text-sm"
        />
        {(Object.keys(FILTER_LABEL) as Filter[]).map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFilter(f)}
            className={`rounded-full border px-3 py-1 text-xs font-medium ${
              filter === f
                ? "border-primary/40 bg-primary/10 text-primary"
                : "border-input text-muted-foreground hover:text-foreground"
            }`}
          >
            {FILTER_LABEL[f]} · {counts[f]}
          </button>
        ))}
        <span className="flex-1" />
        <Link href="/skills/new" className={buttonVariants({ size: "sm" })}>
          New skill
        </Link>
      </div>

      {isLoading && <LoadingState />}
      {isError && <ErrorState message="Couldn't load skills — try refreshing the page." onRetry={() => refetch()} />}
      {!isLoading && !isError && !visible?.length && (
        <EmptyState title="No skills found" message="Try a different search or filter." />
      )}

      {!isLoading && !isError && !!visible?.length && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((s) => (
            <Link
              key={s.name}
              href={`/skills/${s.name}`}
              className="flex flex-col gap-2 rounded-xl border bg-card p-4 text-left shadow-sm transition-colors hover:border-primary"
            >
              <span className="text-sm font-semibold">{s.name}</span>
              <div className="flex flex-wrap gap-1.5">
                <CategoryBadge kind={s.built_in ? "builtin" : "authored"} />
                {s.pinned && <CategoryBadge kind="pinned" />}
              </div>
              <p className="min-h-[34px] flex-1 text-xs text-muted-foreground">{s.description}</p>
              <div className="border-t pt-1.5 text-[11px] text-muted-foreground">
                {s.authored_by ? `by ${s.authored_by}` : "Built-in"}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
