import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/use-me", () => ({ useMe: vi.fn() }));
vi.mock("@/lib/use-models", () => ({ useModels: vi.fn() }));

import { useMe } from "@/lib/use-me";
import { useModels } from "@/lib/use-models";
import { CodexStatusBanner } from "../codex-status-banner";

const mockUseMe = vi.mocked(useMe);
const mockUseModels = vi.mocked(useModels);

function modelsState(codexUsable: boolean) {
  return {
    data: {
      provider: "codex", chat: "gpt-5", build: "gpt-5", review: "gpt-5-mini",
      conflict: false, swap_preview: null,
      providers: [{ name: "codex", usable: codexUsable, hint: "", models: [] }],
      codex_usage: null,
    },
    isLoading: false,
    isError: false,
  };
}

describe("CodexStatusBanner", () => {
  beforeEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockUseMe.mockReturnValue({ data: { email: "a@x.com", is_admin: true } } as any);
  });

  it("shows the subtle connected line when Codex is connected", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockUseModels.mockReturnValue(modelsState(true) as any);
    render(<CodexStatusBanner />);
    expect(screen.getByText("Model: ChatGPT (Codex) — connected")).toBeDefined();
    expect(screen.queryByText("Bott has no model connection")).toBeNull();
  });

  it("shows the warning with a connect CTA for admins when not connected", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockUseModels.mockReturnValue(modelsState(false) as any);
    render(<CodexStatusBanner />);
    expect(screen.getByText("Bott has no model connection")).toBeDefined();
    expect(screen.getByText(/Nothing will work until an admin connects ChatGPT/)).toBeDefined();
    const cta = screen.getByText("Connect ChatGPT");
    expect(cta.closest("a")?.getAttribute("href")).toBe("/admin/models");
  });

  it("shows the warning without an actionable CTA for members", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockUseMe.mockReturnValue({ data: { email: "a@x.com", is_admin: false } } as any);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockUseModels.mockReturnValue(modelsState(false) as any);
    render(<CodexStatusBanner />);
    expect(screen.getByText("Bott has no model connection")).toBeDefined();
    expect(screen.queryByText("Connect ChatGPT")).toBeNull();
    expect(screen.getByText("Ask an admin to connect it.")).toBeDefined();
  });

  it("renders nothing while loading or when the status query errors (members get a 403)", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockUseModels.mockReturnValue({ data: undefined, isLoading: false, isError: true } as any);
    const { container } = render(<CodexStatusBanner />);
    expect(container.firstChild).toBeNull();
  });
});
