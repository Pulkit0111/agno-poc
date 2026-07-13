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
