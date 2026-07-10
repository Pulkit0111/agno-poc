import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
// The Approvals nav item renders a live count badge (admin-only) backed by a
// TanStack query; stub the hook so these render tests need no QueryClient.
vi.mock("@/lib/use-approval-count", () => ({ useApprovalCount: () => ({ data: { pending: 0 } }) }));

import { SidebarNav } from "../sidebar";

describe("SidebarNav", () => {
  it("hides the admin group for members", () => {
    render(<SidebarNav isAdmin={false} />);
    expect(screen.queryByText("Administration")).toBeNull();
    expect(screen.getByText("Approvals")).toBeDefined();
  });

  it("shows the admin group for admins", () => {
    render(<SidebarNav isAdmin={true} />);
    expect(screen.getByText("Administration")).toBeDefined();
    expect(screen.getByText("Models")).toBeDefined();
  });
});
