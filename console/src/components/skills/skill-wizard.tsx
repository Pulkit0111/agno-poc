"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/common/states";
import { Markdown } from "@/components/markdown";
import { useDraftSkill, useSaveSkill, type SkillDraft } from "@/lib/use-skills";
import { ApiError } from "@/lib/api";

const inputClass = "w-full rounded-md border bg-background px-2.5 py-1.5 text-sm";

/** Describe → draft → preview/save. Nothing is persisted until "Save skill". */
export function SkillWizard() {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [what, setWhat] = useState("");
  const [when, setWhen] = useState("");
  const [feedback, setFeedback] = useState("");
  const [draft, setDraft] = useState<SkillDraft | null>(null);
  const [refining, setRefining] = useState(false);

  const draftSkill = useDraftSkill();
  const saveSkill = useSaveSkill();

  function requestDraft(fb: string) {
    setStep(2);
    draftSkill.mutate(
      { what, when, feedback: fb },
      { onSuccess: (data) => { setDraft(data); setStep(3); } },
    );
  }

  function refine() {
    if (!feedback.trim() || refining) return;
    setRefining(true);
    draftSkill.mutate(
      { what, when, feedback },
      {
        onSuccess: (data) => { setDraft(data); setFeedback(""); setRefining(false); },
        onError: () => setRefining(false),
      },
    );
  }

  return (
    <div className="space-y-4">
      <Link href="/skills" className="inline-block text-xs text-primary hover:underline">
        ← All skills
      </Link>
      <div>
        <h1 className="font-display text-lg tracking-tight">New skill</h1>
        <p className="text-sm text-muted-foreground">
          Describe it, Bott drafts it, you review it — nothing is saved until you say so.
        </p>
      </div>

      {step === 1 && (
        <div className="max-w-xl space-y-3 rounded-xl border bg-card p-4 shadow-sm">
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-muted-foreground">What should this skill do?</span>
            <textarea
              className="h-24 w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
              value={what}
              onChange={(e) => setWhat(e.target.value)}
              aria-label="What should this skill do?"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-muted-foreground">When should Bott reach for it?</span>
            <input
              className={inputClass}
              value={when}
              onChange={(e) => setWhen(e.target.value)}
              aria-label="When should Bott reach for it?"
            />
          </label>
          <Button disabled={!what.trim() || !when.trim()} onClick={() => requestDraft("")}>
            Draft it for me
          </Button>
        </div>
      )}

      {step === 2 && (
        <div className="max-w-xl rounded-xl border bg-card p-7 text-center shadow-sm">
          {draftSkill.isError ? (
            <ErrorState
              message={
                draftSkill.error instanceof ApiError
                  ? draftSkill.error.message
                  : "Couldn't draft that skill — try again."
              }
              onRetry={() => requestDraft("")}
            />
          ) : (
            <div>
              <div className="font-display mb-1 text-base">Bott is drafting your skill…</div>
              <div className="text-xs text-muted-foreground">
                Testing it against the repos it can see. Usually under a minute.
              </div>
            </div>
          )}
        </div>
      )}

      {step === 3 && draft && (
        <div className="space-y-3">
          <div className="flex gap-2 rounded-xl border bg-muted/40 px-3 py-2.5 text-sm">
            <p className="text-muted-foreground">
              <b className="font-medium text-foreground">Draft ready.</b> Review it below, then save or refine.
            </p>
          </div>
          <div className="rounded-xl border bg-card p-5 shadow-sm">
            <Markdown content={draft.content} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              disabled={saveSkill.isPending}
              onClick={() =>
                saveSkill.mutate(draft, { onSuccess: (res) => router.push(`/skills/${res.slug}`) })
              }
            >
              Save skill
            </Button>
            <input
              className={`${inputClass} min-w-[200px] flex-1`}
              placeholder="Ask for a change… e.g. 'only weekdays, skip draft PRs'"
              aria-label="Ask for a change"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              disabled={refining}
            />
            <Button variant="outline" disabled={refining || !feedback.trim()} onClick={refine}>
              {refining ? "Refining…" : "Refine"}
            </Button>
            <Button variant="destructive" onClick={() => router.push("/skills")}>
              Discard
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
