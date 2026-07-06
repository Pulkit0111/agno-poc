import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApprovalRow } from "../approval-row";

const APPROVAL = {
  id: 7, user_id: "m@x.com", action: "api:jira",
  summary: "Comment on AXL-142", created: Date.now() / 1000 - 7200,
};

describe("ApprovalRow", () => {
  it("renders system badge, summary and age", () => {
    render(<ApprovalRow approval={APPROVAL} onDecide={() => {}} />);
    expect(screen.getByText("api:jira")).toBeDefined();
    expect(screen.getByText("Comment on AXL-142")).toBeDefined();
    expect(screen.getByText(/2 h ago/)).toBeDefined();
  });

  it("fires decisions", () => {
    const onDecide = vi.fn();
    render(<ApprovalRow approval={APPROVAL} onDecide={onDecide} />);
    fireEvent.click(screen.getByText("Approve"));
    expect(onDecide).toHaveBeenCalledWith(7, true);
    fireEvent.click(screen.getByText("Dismiss"));
    expect(onDecide).toHaveBeenCalledWith(7, false);
  });
});
