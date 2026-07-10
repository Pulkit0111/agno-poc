// Single source of truth for status/verdict colours across the console.
// Consolidates the previously-duplicated colour maps in job-drawer.tsx,
// admin/policy/page.tsx and review-trends-chart.tsx.

export type Tone = "good" | "warn" | "bad" | "neutral" | "accent";

export type StatusMeta = { label: string; tone: Tone };

/** Tailwind class strings per tone — matches the outline-pill idiom already used across pages. */
export const toneClass: Record<Tone, string> = {
  good: "text-green-700 dark:text-green-400 border-green-600/30",
  warn: "text-amber-700 dark:text-amber-400 border-amber-600/30",
  bad: "text-red-700 dark:text-red-400 border-red-600/30",
  neutral: "text-muted-foreground border-border",
  accent: "text-primary border-primary/30",
};

/** Job / queue statuses the app renders (see job-drawer.tsx and the home dashboard). */
const JOB_STATUS: Record<string, StatusMeta> = {
  pending: { label: "Pending", tone: "neutral" },
  queued: { label: "Queued", tone: "accent" },
  running: { label: "Running", tone: "warn" },
  done: { label: "Done", tone: "good" },
  failed: { label: "Failed", tone: "bad" },
};

/** PR review verdicts and policy verdicts. */
const VERDICT: Record<string, StatusMeta> = {
  // PR review
  approve: { label: "Approve", tone: "good" },
  comment: { label: "Comment", tone: "warn" },
  request_changes: { label: "Request changes", tone: "bad" },
  // policy classification
  allow: { label: "Allow", tone: "good" },
  gate: { label: "Gate", tone: "warn" },
  deny: { label: "Deny", tone: "bad" },
};

function fallback(value: string): StatusMeta {
  return { label: value, tone: "neutral" };
}

export function jobStatusMeta(status: string): StatusMeta {
  return JOB_STATUS[status] ?? fallback(status);
}

export function verdictMeta(verdict: string): StatusMeta {
  return VERDICT[verdict] ?? fallback(verdict);
}

/** Resolve a job status OR a verdict to its label + tone. */
export function statusMeta(value: string): StatusMeta {
  return JOB_STATUS[value] ?? VERDICT[value] ?? fallback(value);
}

/** Tailwind classes for a raw status/verdict string, ready to drop onto a pill. */
export function statusClass(value: string): string {
  return toneClass[statusMeta(value).tone];
}
