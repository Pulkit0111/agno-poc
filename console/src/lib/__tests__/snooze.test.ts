import { describe, expect, it } from "vitest";
import { nextMondayMorning, pickedDateMorning, tomorrowMorning } from "../snooze";

// Wed Jan 10 2024, 15:30 local.
const WED = new Date(2024, 0, 10, 15, 30, 0);
// Mon Jan 8 2024, 09:00 local — exercises the "today is Monday" edge case.
const MON = new Date(2024, 0, 8, 9, 0, 0);

function atNine(y: number, m: number, d: number): number {
  return new Date(y, m, d, 9, 0, 0, 0).getTime() / 1000;
}

describe("tomorrowMorning", () => {
  it("is 9am the next calendar day, regardless of current time", () => {
    expect(tomorrowMorning(WED)).toBe(atNine(2024, 0, 11));
  });

  it("still rolls forward a day when now is already past 9am", () => {
    expect(tomorrowMorning(MON)).toBe(atNine(2024, 0, 9));
  });
});

describe("nextMondayMorning", () => {
  it("finds the upcoming Monday when today isn't one", () => {
    expect(nextMondayMorning(WED)).toBe(atNine(2024, 0, 15));
  });

  it("skips to next week's Monday when today already is Monday", () => {
    expect(nextMondayMorning(MON)).toBe(atNine(2024, 0, 15));
  });
});

describe("pickedDateMorning", () => {
  it("parses a date-input value (YYYY-MM-DD) as 9am local on that day", () => {
    expect(pickedDateMorning("2024-07-20")).toBe(atNine(2024, 6, 20));
  });
});
