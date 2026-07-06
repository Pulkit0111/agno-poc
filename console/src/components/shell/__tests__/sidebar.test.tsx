import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

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
