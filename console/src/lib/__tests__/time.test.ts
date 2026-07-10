import { describe, expect, it } from "vitest";
import { relativeTime } from "../time";

describe("relativeTime", () => {
  const now = Date.now() / 1000;
  it("says just now under a minute", () => expect(relativeTime(now - 20)).toBe("just now"));
  it("minutes", () => expect(relativeTime(now - 5 * 60)).toBe("5 m ago"));
  it("hours", () => expect(relativeTime(now - 2 * 3600)).toBe("2 h ago"));
  it("days", () => expect(relativeTime(now - 3 * 86400)).toBe("3 d ago"));
  it("weeks", () => expect(relativeTime(now - 14 * 86400)).toBe("2 w ago"));
  it("months", () => expect(relativeTime(now - 60 * 86400)).toBe("2 mo ago"));
  it("years", () => expect(relativeTime(now - 400 * 86400)).toBe("1 y ago"));
});
