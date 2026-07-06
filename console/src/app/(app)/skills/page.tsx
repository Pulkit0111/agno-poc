"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/lib/use-me";
import { usePinSkill, useRetireSkill, useSkills } from "@/lib/use-skills";

export default function SkillsPage() {
  const { data: me } = useMe();
  const { data: skills, isLoading } = useSkills();
  const pin = usePinSkill();
  const retire = useRetireSkill();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Skills</h1>
        <p className="text-sm text-muted-foreground">What Bott has learned to do — built-in and authored by the team</p>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {isLoading && <><Skeleton className="h-28" /><Skeleton className="h-28" /></>}
        {skills?.map((s) => (
          <div key={s.name} className="rounded-xl border bg-card p-4 shadow-sm">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold">{s.name}</span>
              <Badge variant="outline" className={s.built_in ? "text-primary" : "text-green-700 dark:text-green-400"}>
                {s.built_in ? "built-in" : "authored"}
              </Badge>
              {s.pinned && <Badge variant="outline">pinned</Badge>}
            </div>
            <p className="mt-2 min-h-[34px] text-xs text-muted-foreground">{s.description}</p>
            {!s.built_in && (
              <div className="mt-1 text-[11px] text-muted-foreground">by {s.authored_by}</div>
            )}
            {me?.is_admin && !s.built_in && (
              <div className="mt-3 flex gap-1.5">
                <Button size="sm" variant="outline" onClick={() => pin.mutate({ name: s.name, pinned: !s.pinned })}>
                  {s.pinned ? "Unpin" : "Pin"}
                </Button>
                <Button size="sm" variant="ghost" disabled={s.pinned} onClick={() => retire.mutate(s.name)}>
                  Retire
                </Button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
