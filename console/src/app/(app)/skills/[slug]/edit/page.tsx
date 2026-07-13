"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import { Markdown } from "@/components/markdown";
import { useMe } from "@/lib/use-me";
import { useSkill, useUpdateSkill } from "@/lib/use-skills";
import { joinFrontmatter, splitFrontmatter } from "@/lib/skill-content";

export default function SkillEditPage() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug;
  const router = useRouter();
  const { data: me, isLoading: meLoading } = useMe();
  const { data: skill, isLoading, isError, refetch } = useSkill(slug);
  const update = useUpdateSkill(slug);

  const frontmatterRef = useRef("");
  const [originalBody, setOriginalBody] = useState("");
  const [body, setBody] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    // Hydrating locally-editable state from data that loads asynchronously —
    // not derived/synced state, so the usual "don't setState in an effect" advice
    // doesn't apply here (mirrors admin/prompts/page.tsx's identical pattern).
    if (!skill) return;
    const { frontmatter, body: b } = splitFrontmatter(skill.content);
    frontmatterRef.current = frontmatter;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOriginalBody(b);
    setBody(b);
  }, [skill]);

  if (isLoading || meLoading) return <LoadingState />;
  if (isError || !skill) {
    return <ErrorState message="Couldn't load that skill." onRetry={() => refetch()} />;
  }

  if (skill.built_in) {
    return (
      <EmptyState
        title="Built-in skills can't be edited"
        message="Built-in skills are maintained in code review. Propose changes in #bott-testing, or author your own variant."
      />
    );
  }

  const isOwner = !!me?.email && !!skill.authored_by && me.email.toLowerCase() === skill.authored_by.toLowerCase();
  if (!me?.is_admin && !isOwner) {
    return <EmptyState title="Not your skill" message="Only this skill's author or an admin can edit it." />;
  }

  function save() {
    const content = joinFrontmatter(frontmatterRef.current, body);
    update.mutate(
      { content, note },
      { onSuccess: () => router.push(`/skills/${slug}`) },
    );
  }

  return (
    <div className="space-y-4">
      <Link href={`/skills/${slug}`} className="inline-block text-xs text-primary hover:underline">
        ← {slug}
      </Link>
      <div>
        <h1 className="font-display text-lg tracking-tight">Edit skill</h1>
        <p className="text-sm text-muted-foreground">
          Changes apply to Bott immediately after saving — a new version is kept, so you can always roll back.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground" htmlFor="skill-src">
            SKILL.md source
          </label>
          <textarea
            id="skill-src"
            className="h-[420px] w-full rounded-md border bg-background px-2.5 py-1.5 font-mono text-xs leading-relaxed"
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
        </div>
        <div>
          <span className="mb-1 block text-xs font-medium text-muted-foreground">Preview</span>
          <div className="h-[420px] overflow-y-auto rounded-md border bg-card p-4">
            <Markdown content={body} />
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input
          className="w-full max-w-sm rounded-md border bg-background px-2.5 py-1.5 text-sm"
          placeholder="What changed and why (required)"
          aria-label="Version note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <Button
          disabled={!note.trim() || !body.trim() || body === originalBody || update.isPending}
          onClick={save}
        >
          Save changes
        </Button>
        <Button variant="outline" onClick={() => router.push(`/skills/${slug}`)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
