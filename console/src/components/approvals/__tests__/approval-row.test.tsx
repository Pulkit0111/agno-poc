import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Decision buttons only render for admins; drive the role via a mocked useMe.
let mockIsAdmin = true;
vi.mock("@/lib/use-me", () => ({ useMe: () => ({ data: { email: "a@x.com", is_admin: mockIsAdmin } }) }));

import { ApprovalRow } from "../approval-row";

const APPROVAL = {
  id: 7, user_id: "m@x.com", action: "api:jira",
  summary: "Comment on AXL-142", created: Date.now() / 1000 - 7200,
};

afterEach(() => { mockIsAdmin = true; });

describe("ApprovalRow", () => {
  it("renders system badge, summary and age", () => {
    render(<ApprovalRow approval={APPROVAL} onDecide={() => {}} />);
    expect(screen.getByText("api:jira")).toBeDefined();
    expect(screen.getByText("Comment on AXL-142")).toBeDefined();
    expect(screen.getByText(/2 h ago/)).toBeDefined();
  });

  it("fires decisions for admins", () => {
    const onDecide = vi.fn();
    render(<ApprovalRow approval={APPROVAL} onDecide={onDecide} />);
    fireEvent.click(screen.getByText("Approve & run"));
    expect(onDecide).toHaveBeenCalledWith(7, true);
    fireEvent.click(screen.getByText("Dismiss"));
    expect(onDecide).toHaveBeenCalledWith(7, false);
  });

  it("hides decision buttons for members", () => {
    mockIsAdmin = false;
    render(<ApprovalRow approval={APPROVAL} onDecide={() => {}} />);
    expect(screen.queryByText("Approve & run")).toBeNull();
    expect(screen.queryByText("Dismiss")).toBeNull();
    expect(screen.getByText(/Awaiting admin/i)).toBeDefined();
  });
});
