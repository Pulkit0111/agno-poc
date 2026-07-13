/**
 * Pure date math backing the action-item snooze menu (Tomorrow morning / Next week /
 * Pick a date…). Kept free of React/hooks so the three computations are trivial to unit
 * test against a fixed `now`. All return epoch seconds — the shape `remind_at` wants.
 */

function atLocalTime(date: Date, hour: number, minute: number): Date {
  const d = new Date(date);
  d.setHours(hour, minute, 0, 0);
  return d;
}

function toEpochSeconds(date: Date): number {
  return Math.floor(date.getTime() / 1000);
}

/** Tomorrow at 9:00 local time — always the next calendar day, even if `now` is already past 9am. */
export function tomorrowMorning(now: Date = new Date()): number {
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  return toEpochSeconds(atLocalTime(tomorrow, 9, 0));
}

/** The next Monday at 9:00 local — strictly in the future, so if `now` is already a
 * Monday this lands on the Monday a full week out, not today. */
export function nextMondayMorning(now: Date = new Date()): number {
  const day = now.getDay(); // 0=Sun .. 6=Sat
  let daysUntilMonday = (1 - day + 7) % 7;
  if (daysUntilMonday === 0) daysUntilMonday = 7;
  const monday = new Date(now);
  monday.setDate(monday.getDate() + daysUntilMonday);
  return toEpochSeconds(atLocalTime(monday, 9, 0));
}

/** A `<input type="date">` value ("YYYY-MM-DD") at 9:00 local on that day. */
export function pickedDateMorning(dateStr: string): number {
  const [y, m, d] = dateStr.split("-").map(Number);
  return toEpochSeconds(new Date(y, m - 1, d, 9, 0, 0, 0));
}

function localDayStartMs(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** Short "due …" label for a snoozed item's remind_at (epoch seconds).
 * Compares LOCAL CALENDAR days, not elapsed hours — 9pm today vs 9am tomorrow is
 * "due tomorrow", never "due today". Math.round on the day-start diff absorbs DST's
 * 23/25-hour days. */
export function dueLabel(remindAt: number, now: Date = new Date()): string {
  const due = new Date(remindAt * 1000);
  const days = Math.round((localDayStartMs(due) - localDayStartMs(now)) / 86400000);
  if (days <= 0) return "due today";
  if (days === 1) return "due tomorrow";
  if (days < 7) return `due ${due.toLocaleDateString(undefined, { weekday: "short" })}`;
  return `due ${due.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}
