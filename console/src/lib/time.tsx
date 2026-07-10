/** Accepts epoch-seconds (number or numeric string) or an ISO date string. */
function toEpochSeconds(value: number | string): number {
  if (typeof value === "number") return value;
  const trimmed = value.trim();
  if (trimmed !== "") {
    const n = Number(trimmed);
    if (!Number.isNaN(n)) return n; // numeric string = epoch seconds
  }
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? Date.now() / 1000 : ms / 1000;
}

/** Short "time ago" label. Handles seconds → years so we never render "400 d ago". */
export function relativeTime(value: number | string): string {
  const s = Date.now() / 1000 - toEpochSeconds(value);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const days = Math.floor(s / 86400);
  if (days < 7) return `${days} d ago`;
  if (days < 30) return `${Math.floor(days / 7)} w ago`;
  if (days < 365) return `${Math.floor(days / 30)} mo ago`;
  return `${Math.floor(days / 365)} y ago`;
}

/** Absolute local date-time with timezone abbreviation, e.g. "10 Jul 2026, 2:14 PM GMT+5:30". */
export function absoluteTime(value: number | string): string {
  return new Date(toEpochSeconds(value) * 1000).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZoneName: "short",
  });
}

/** Relative time with the full local timestamp (incl. timezone) in the `title` tooltip. */
export function Time({
  value,
  className,
}: {
  value: number | string;
  className?: string;
}) {
  const epoch = toEpochSeconds(value);
  return (
    <time
      dateTime={new Date(epoch * 1000).toISOString()}
      title={absoluteTime(value)}
      className={className}
    >
      {relativeTime(value)}
    </time>
  );
}
