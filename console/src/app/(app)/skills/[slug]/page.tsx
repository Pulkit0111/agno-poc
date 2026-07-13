"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Info } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { CategoryBadge } from "@/components/ui/category-badge";
import { ErrorState, LoadingState } from "@/components/common/states";
import { Markdown } from "@/components/markdown";
import { relativeTime } from "@/lib/time";
import { useMe } from "@/lib/use-me";
import { usePinSkill, useRetireSkill, useSkill } from "@/lib/use-skills";
import { splitFrontmatter } from "@/lib/skill-content";

export default function SkillDetailPage() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug;
  const router = useRouter();
  const { data: me, isLoading: meLoading } = useMe();
  const { data: skill, isLoading, isError, refetch } = useSkill(slug);
  const pin = usePinSkill();
  const retire = useRetireSkill();

  if (isLoading || meLoading) return <LoadingState />;
  if (isError || !skill) {
    return <ErrorState message="Couldn't load that skill." onRetry={() => refetch()} />;
  }

  const isOwner = !!me?.email && !!skill.authored_by && me.email.toLowerCase() === skill.authored_by.toLowerCase();
  const canEdit = !skill.built_in && (me?.is_admin || isOwner);
  const canManage = !skill.built_in && me?.is_admin;
  const { body } = splitFrontmatter(skill.content);

  const ledeParts: string[] = [];
  if (skill.built_in) {
    ledeParts.push("Curated in the codebase", "read-only");
  } else {
    if (skill.authored_by) ledeParts.push(`by ${skill.authored_by}`);
    if (skill.versions.length) ledeParts.push(`v${skill.versions.length}`);
  }

  return (
    <div className="space-y-4">
      <Link href="/skills" className="inline-block text-xs text-primary hover:underline">
        ← All skills
      </Link>

      <div>
        <h1 className="flex flex-wrap items-center gap-2">
          <span className="font-display text-lg tracking-tight">{skill.name}</span>
          <CategoryBadge kind={skill.built_in ? "builtin" : "authored"} />
          {skill.pinned && <CategoryBadge kind="pinned" />}
        </h1>
        {!!ledeParts.length && <p className="text-sm text-muted-foreground">{ledeParts.join(" · ")}</p>}
      </div>

      {(canEdit || canManage) && (
        <div className="flex flex-wrap gap-2">
          {canEdit && (
            <Link href={`/skills/${slug}/edit`} className={buttonVariants({ size: "sm" })}>
              Edit skill
            </Link>
          )}
          {canManage && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => pin.mutate({ name: slug, pinned: !skill.pinned })}
            >
              {skill.pinned ? "Unpin" : "Pin"}
            </Button>
          )}
          {canManage && (
            <Button
              size="sm"
              variant="destructive"
              disabled={skill.pinned}
              title={skill.pinned ? "Unpin this skill before retiring it." : undefined}
              onClick={() => retire.mutate(slug, { onSuccess: () => router.push("/skills") })}
            >
              Retire
            </Button>
          )}
        </div>
      )}

      {skill.built_in && (
        <div className="flex gap-2 rounded-xl border bg-muted/40 px-3 py-2.5 text-sm">
          <Info className="mt-0.5 size-4 flex-none text-muted-foreground" />
          <p className="max-w-[65ch] text-muted-foreground">
            Built-in skills ship with Bott and are maintained in code review. To change one, propose it in{" "}
            <b className="font-medium text-foreground">#bott-testing</b> — or author your own variant.
          </p>
        </div>
      )}

      <div className="rounded-xl border bg-card p-5 shadow-sm">
        <Markdown content={body} />
      </div>

      {!skill.built_in && (
        <div className="rounded-xl border bg-card shadow-sm">
          <div className="border-b px-4 py-2.5 text-sm font-semibold">Version history</div>
          {!skill.versions.length ? (
            <div className="px-4 py-6 text-sm text-muted-foreground">No saved versions yet.</div>
          ) : (
            <ul>
              {skill.versions.map((v) => (
                <li key={v.id} className="border-b px-4 py-3 last:border-b-0">
                  <div className="text-sm font-medium">{v.note}</div>
                  <div className="text-xs text-muted-foreground">
                    {v.author} · {relativeTime(v.created)}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
