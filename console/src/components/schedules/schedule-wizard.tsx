"use client";

import { useEffect, useRef, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useCreateSchedule, useSchedulePreview, type SchedulePreview } from "@/lib/use-schedules";

type Kind = "sprint" | "delivery" | "security" | "dsm" | "portfolio" | "sentiment";

const KINDS: { value: Kind; label: string; description: string }[] = [
  { value: "sprint", label: "Sprint report", description: "Designed HTML report from live Jira" },
  { value: "delivery", label: "Delivery digest", description: "Engagement status rollup" },
  { value: "security", label: "Security advisories", description: "Drupal SA digest with project matching" },
  { value: "dsm", label: "Daily standup", description: "Open, pre-read & summarize" },
  { value: "portfolio", label: "Portfolio snapshot", description: "Risk rollup across engagements" },
  { value: "sentiment", label: "Sentiment report", description: "Team sentiment trend, tracked over time" },
];

const FREQUENCIES: { value: string; label: string }[] = [
  { value: "daily", label: "Daily" },
  { value: "weekdays", label: "Weekdays" },
  { value: "weekly", label: "Weekly" },
];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

const inputClass = "w-full rounded-md border bg-background px-2.5 py-1.5 text-sm";

export function ScheduleWizard({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [step, setStep] = useState(1);
  const [kind, setKind] = useState<Kind>("sprint");
  const [channel, setChannel] = useState("");
  const [engagement, setEngagement] = useState("");
  const [accountName, setAccountName] = useState("");
  const [band, setBand] = useState("");
  const [team, setTeam] = useState("");
  const [frequency, setFrequency] = useState("daily");
  const [time, setTime] = useState("09:00");

  const create = useCreateSchedule();
  const preview = useSchedulePreview();
  // Latest-wins guard for the preview: each request takes a sequence number and only the
  // newest may publish its result, so overlapping responses resolving out of order can
  // never leave a stale next-run on screen.
  const previewSeq = useRef(0);
  const [previewData, setPreviewData] = useState<SchedulePreview | null>(null);

  const needsEngagement = kind === "sprint" || kind === "delivery";
  const needsTeam = kind === "dsm";
  const needsFrequency = kind !== "sprint";
  const isDelivery = kind === "delivery";

  const detailsValid =
    channel.trim() !== "" &&
    (!needsEngagement || engagement.trim() !== "") &&
    (!needsTeam || team.trim() !== "");

  // Live next-run preview — recomputed whenever the cadence inputs change while step 3 is
  // showing. Sprint has no frequency choice (fixed weekly, pinned to the sprint's own end
  // day server-side), so there's nothing meaningful to preview for it.
  useEffect(() => {
    if (step !== 3 || !needsFrequency) return;
    const seq = ++previewSeq.current;
    preview.mutate(
      { kind, frequency, time },
      { onSuccess: (data) => { if (seq === previewSeq.current) setPreviewData(data); } },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, needsFrequency, kind, frequency, time]);

  function selectKind(k: Kind) {
    setKind(k);
    setFrequency(k === "dsm" ? "weekdays" : "daily");
  }

  function submit() {
    create.mutate(
      {
        kind,
        channel,
        time,
        frequency: needsFrequency ? frequency : undefined,
        engagement: needsEngagement ? engagement : undefined,
        account_name: isDelivery ? (accountName || undefined) : undefined,
        band: isDelivery ? (band || undefined) : undefined,
        team: needsTeam ? team : undefined,
      },
      { onSuccess: () => onOpenChange(false) },
    );
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-black/10 transition-opacity duration-150 data-ending-style:opacity-0 data-starting-style:opacity-0 supports-backdrop-filter:backdrop-blur-xs" />
        <Dialog.Popup className="fixed top-1/2 left-1/2 z-50 flex w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-xl border bg-popover bg-clip-padding p-5 text-sm text-popover-foreground shadow-lg transition duration-200 data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0">
          <div className="flex items-center justify-between">
            <Dialog.Title className="font-heading text-base font-medium text-foreground">
              New schedule
            </Dialog.Title>
            <div className="flex gap-1">
              {[1, 2, 3].map((s) => (
                <span
                  key={s}
                  className={cn("size-1.5 rounded-full", s === step ? "bg-primary" : "bg-muted")}
                />
              ))}
            </div>
          </div>

          {step === 1 && (
            <div>
              <p className="mb-2 text-sm">What should Bott do on a schedule?</p>
              <div className="grid grid-cols-2 gap-2">
                {KINDS.map((k) => (
                  <button
                    key={k.value}
                    type="button"
                    onClick={() => selectKind(k.value)}
                    className={cn(
                      "rounded-lg border px-3 py-2.5 text-left transition-colors",
                      kind === k.value ? "border-primary bg-accent" : "hover:bg-muted/50",
                    )}
                  >
                    <div className="text-sm font-medium">{k.label}</div>
                    <div className="text-xs text-muted-foreground">{k.description}</div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-3">
              {needsEngagement && (
                <Field label="Engagement">
                  <input
                    className={inputClass}
                    value={engagement}
                    onChange={(e) => setEngagement(e.target.value)}
                    placeholder="acme-commerce"
                  />
                </Field>
              )}
              {needsTeam && (
                <Field label="Team">
                  <input
                    className={inputClass}
                    value={team}
                    onChange={(e) => setTeam(e.target.value)}
                    placeholder="Team Falcon"
                  />
                </Field>
              )}
              <Field label="Channel">
                <input
                  className={inputClass}
                  value={channel}
                  onChange={(e) => setChannel(e.target.value)}
                  placeholder="#proj-acme"
                />
              </Field>
              {isDelivery && (
                <>
                  <Field label="Account name (optional)">
                    <input className={inputClass} value={accountName} onChange={(e) => setAccountName(e.target.value)} />
                  </Field>
                  <Field label="Band (optional)">
                    <input className={inputClass} value={band} onChange={(e) => setBand(e.target.value)} />
                  </Field>
                </>
              )}
            </div>
          )}

          {step === 3 && (
            <div className="space-y-3">
              {needsFrequency ? (
                <>
                  <Field label="How often?">
                    <div className="flex gap-1.5">
                      {FREQUENCIES.map((f) => (
                        <button
                          key={f.value}
                          type="button"
                          onClick={() => setFrequency(f.value)}
                          className={cn(
                            "rounded-full border px-3 py-1 text-xs font-medium",
                            frequency === f.value ? "border-primary bg-accent text-accent-foreground" : "hover:bg-muted/50",
                          )}
                        >
                          {f.label}
                        </button>
                      ))}
                    </div>
                  </Field>
                  <Field label="At what time?">
                    <input type="time" className={cn(inputClass, "max-w-[140px]")} value={time} onChange={(e) => setTime(e.target.value)} />
                  </Field>
                  {previewData && (
                    <div className="rounded-lg border bg-muted/40 px-3 py-2 text-xs">
                      Next run: <b className="font-medium">{previewData.next_run}</b>
                      {channel && (
                        <>
                          {" "}· posts to <b className="font-medium">{channel}</b>
                        </>
                      )}
                      <div className="mt-0.5 text-muted-foreground">{previewData.cadence}</div>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <p className="text-xs text-muted-foreground">
                    Sprint reports run once a week, timed automatically to your sprint&apos;s last day.
                  </p>
                  <Field label="At what time?">
                    <input type="time" className={cn(inputClass, "max-w-[140px]")} value={time} onChange={(e) => setTime(e.target.value)} />
                  </Field>
                </>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2">
            {step > 1 && (
              <Button variant="outline" size="sm" onClick={() => setStep(step - 1)}>
                Back
              </Button>
            )}
            {step < 3 && (
              <Button size="sm" onClick={() => setStep(step + 1)} disabled={step === 2 && !detailsValid}>
                Next
              </Button>
            )}
            {step === 3 && (
              <Button size="sm" onClick={submit} disabled={create.isPending}>
                Create schedule
              </Button>
            )}
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
