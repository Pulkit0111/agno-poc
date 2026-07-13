import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KindChip } from "../kind-chip";
import { CategoryBadge } from "../category-badge";

describe("KindChip", () => {
  it("renders its label", () => {
    render(<KindChip>{"api:jira"}</KindChip>);
    expect(screen.getByText("api:jira")).toBeDefined();
  });

  it("renders as a mono neutral chip", () => {
    render(<KindChip>{"api:jira"}</KindChip>);
    const el = screen.getByText("api:jira");
    expect(el.className).toContain("font-mono");
    expect(el.className).toContain("bg-secondary");
  });
});

describe("CategoryBadge", () => {
  it("renders the built-in label", () => {
    render(<CategoryBadge kind="builtin" />);
    expect(screen.getByText("Built-in")).toBeDefined();
  });

  it("renders the authored label with the accent tint", () => {
    render(<CategoryBadge kind="authored" />);
    const el = screen.getByText("Authored");
    expect(el.className).toContain("bg-accent");
    expect(el.className).toContain("text-accent-foreground");
  });

  it("renders the pinned label with the warning tint", () => {
    render(<CategoryBadge kind="pinned" />);
    const el = screen.getByText("Pinned");
    expect(el.className).toContain("amber");
  });

  it("renders the admin label with the accent tint", () => {
    render(<CategoryBadge kind="admin" />);
    const el = screen.getByText("Admin");
    expect(el.className).toContain("bg-accent");
  });

  it("renders the member label as a neutral chip", () => {
    render(<CategoryBadge kind="member" />);
    const el = screen.getByText("Member");
    expect(el.className).toContain("bg-secondary");
  });

  it("renders the personal label with the accent tint", () => {
    render(<CategoryBadge kind="personal" />);
    const el = screen.getByText("Personal");
    expect(el.className).toContain("bg-accent");
  });

  it("renders the invited label as a neutral chip", () => {
    render(<CategoryBadge kind="invited" />);
    const el = screen.getByText("Invited");
    expect(el.className).toContain("bg-secondary");
  });

  it("applies a caller-provided className alongside the variant classes", () => {
    render(<CategoryBadge kind="builtin" className="ml-2" />);
    expect(screen.getByText("Built-in").className).toContain("ml-2");
  });
});
