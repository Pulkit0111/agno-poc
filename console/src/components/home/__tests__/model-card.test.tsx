import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/use-me", () => ({ useMe: vi.fn() }));
vi.mock("@/lib/use-models", async () => {
  const actual = await vi.importActual<typeof import("@/lib/use-models")>("@/lib/use-models");
  return { ...actual, useModels: vi.fn() };
});

import { useMe } from "@/lib/use-me";
import { useModels } from "@/lib/use-models";
import { ModelCard } from "../model-card";

const mockUseMe = vi.mocked(useMe);
const mockUseModels = vi.mocked(useModels);

describe("ModelCard", () => {
  it("reads the member shape (active.*) and hides the manage link", () => {
    mockUseMe.mockReturnValue({ data: { email: "m@x.com", is_admin: false } } as unknown as ReturnType<typeof useMe>);
    mockUseModels.mockReturnValue({
      data: {
        active: { provider: "codex", chat: "gpt-5.5", build: "gpt-5.5", review: "gpt-5.4" },
        providers: [{ name: "codex", usable: true, hint: null, models: [] }],
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useModels>);

    render(<ModelCard />);

    expect(screen.getByText("ChatGPT (Codex) connected")).toBeDefined();
    expect(screen.getAllByText("gpt-5.5")).toHaveLength(2);
    expect(screen.getByText("gpt-5.4")).toBeDefined();
    expect(screen.queryByText("Manage models →")).toBeNull();
  });

  it("reads the admin flat shape and shows the manage link", () => {
    mockUseMe.mockReturnValue({ data: { email: "a@x.com", is_admin: true } } as unknown as ReturnType<typeof useMe>);
    mockUseModels.mockReturnValue({
      data: {
        provider: "codex", chat: "gpt-5.5", build: "gpt-5.5", review: "gpt-5.4",
        conflict: false, swap_preview: null,
        providers: [{ name: "codex", usable: false, hint: null, models: [] }],
        codex_usage: null,
        // Task 3 made `active`/`catalogs` additive to the admin payload too — the flat
        // fields above stay for back-compat, but `catalogs` is what now discriminates
        // admin from member (see isAdminModels).
        active: {
          provider: "codex", chat: "gpt-5.5", build: "gpt-5.5", review: "gpt-5.4",
          providers_by_role: { chat: "codex", build: "codex", review: "codex" },
        },
        catalogs: { codex: ["gpt-5.5", "gpt-5.4"], openrouter: [], bedrock: [] },
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useModels>);

    render(<ModelCard />);

    expect(screen.getByText("ChatGPT (Codex) not connected")).toBeDefined();
    expect(screen.getByText("Manage models →")).toBeDefined();
  });

  it("renders nothing while loading or on error", () => {
    mockUseMe.mockReturnValue({ data: undefined } as unknown as ReturnType<typeof useMe>);
    mockUseModels.mockReturnValue({ data: undefined, isLoading: true, isError: false } as unknown as ReturnType<typeof useModels>);
    const { container } = render(<ModelCard />);
    expect(container.firstChild).toBeNull();
  });
});
