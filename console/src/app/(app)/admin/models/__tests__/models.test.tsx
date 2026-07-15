import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/use-models", async () => {
  const actual = await vi.importActual<typeof import("@/lib/use-models")>("@/lib/use-models");
  return { ...actual, useModels: vi.fn(), useSetModelOverride: vi.fn() };
});
vi.mock("@/lib/use-me", async () => {
  const actual = await vi.importActual<typeof import("@/lib/use-me")>("@/lib/use-me");
  return { ...actual, useMe: vi.fn() };
});
// The codex-connect card pulls in its own mutations/polling — irrelevant to this page's
// model pickers, so stub it out to a simple marker.
vi.mock("@/components/system/codex-connect", () => ({
  CodexConnect: ({ connected }: { connected: boolean }) => (
    <div data-testid="codex-connect">{connected ? "codex connected" : "codex not connected"}</div>
  ),
}));

import { useMe } from "@/lib/use-me";
import { AdminModelsState, useModels, useSetModelOverride } from "@/lib/use-models";
import ModelsPage from "../page";

const mockUseMe = vi.mocked(useMe);
const mockUseModels = vi.mocked(useModels);
const mockUseSetModelOverride = vi.mocked(useSetModelOverride);

let mutate: ReturnType<typeof vi.fn>;

const BASE_DATA: AdminModelsState = {
  provider: "codex", chat: "gpt-5.5", build: "gpt-5.5-codex", review: "gpt-5.4",
  conflict: false, swap_preview: null,
  providers: [
    { name: "codex", usable: true, hint: null, models: ["gpt-5.5", "gpt-5.5-codex", "gpt-5.4"] },
  ],
  codex_usage: null,
  active: {
    provider: "codex", chat: "gpt-5.5", build: "gpt-5.5-codex", review: "gpt-5.4",
  },
  catalogs: {
    codex: ["gpt-5.5", "gpt-5.5-codex", "gpt-5.4"],
  },
};

function setData(overrides: Partial<AdminModelsState> = {}) {
  mockUseModels.mockReturnValue({
    data: { ...BASE_DATA, ...overrides },
    isLoading: false, isError: false, error: null, refetch: vi.fn(),
  } as unknown as ReturnType<typeof useModels>);
}

beforeEach(() => {
  mutate = vi.fn();
  mockUseMe.mockReturnValue({
    data: { email: "admin@axelerant.com", is_admin: true }, isLoading: false, isError: false,
  } as unknown as ReturnType<typeof useMe>);
  mockUseSetModelOverride.mockReturnValue({
    mutate, isPending: false,
  } as unknown as ReturnType<typeof useSetModelOverride>);
  setData();
});

describe("ModelsPage", () => {
  it("renders the three jobs, each with a model dropdown and no provider dropdown", () => {
    render(<ModelsPage />);
    for (const label of ["Chat", "Build", "Review"]) {
      expect(screen.getByText(label)).toBeDefined();
    }
    expect(screen.getByLabelText("Chat model")).toBeDefined();
    expect(screen.getByLabelText("Build model")).toBeDefined();
    expect(screen.getByLabelText("Review model")).toBeDefined();
    // Codex is the only provider — no per-role provider pickers.
    expect(screen.queryByLabelText("Chat provider")).toBeNull();
    expect(screen.queryByLabelText("Build provider")).toBeNull();
    expect(screen.queryByLabelText("Review provider")).toBeNull();
  });

  it("drops all OpenRouter/Bedrock provider copy", () => {
    render(<ModelsPage />);
    expect(screen.getByText("Pick which Codex model handles each job")).toBeDefined();
    expect(screen.queryByText(/openrouter/i)).toBeNull();
    expect(screen.queryByText(/bedrock/i)).toBeNull();
  });

  it("shows the model dropdown fed by the codex catalog", () => {
    render(<ModelsPage />);
    const select = screen.getByLabelText("Chat model") as HTMLSelectElement;
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["gpt-5.5", "gpt-5.5-codex", "gpt-5.4"]);
    expect(select.value).toBe("gpt-5.5");
  });

  it("changing the model dropdown fires the model mutation", () => {
    render(<ModelsPage />);
    const modelSelect = screen.getByLabelText("Chat model") as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: "gpt-5.4" } });
    expect(mutate).toHaveBeenCalledWith({ key: "model.chat", value: "gpt-5.4" });
  });

  it("passes codex connection state through to the connect card", () => {
    render(<ModelsPage />);
    expect(screen.getByTestId("codex-connect").textContent).toBe("codex connected");
  });

  it("tells the connect card when codex is not connected", () => {
    setData({
      providers: [{ name: "codex", usable: false, hint: "Connect ChatGPT to enable Codex", models: [] }],
    });
    render(<ModelsPage />);
    expect(screen.getByTestId("codex-connect").textContent).toBe("codex not connected");
  });

  it("shows a connect hint instead of a model dropdown when the codex catalog is empty", () => {
    setData({
      providers: [{ name: "codex", usable: false, hint: "Connect ChatGPT to enable Codex", models: [] }],
      catalogs: { codex: [] },
    });
    render(<ModelsPage />);
    expect(screen.queryByLabelText("Chat model")).toBeNull();
    expect(screen.getAllByText("Connect ChatGPT to enable Codex")).toHaveLength(3);
  });

  it("keeps the review anti-affinity banner when review equals build", () => {
    setData({
      review: "gpt-5.5-codex",
      conflict: true, swap_preview: "gpt-5.4",
      active: { ...BASE_DATA.active, review: "gpt-5.5-codex" },
    });
    render(<ModelsPage />);
    const banner = screen.getByText("Review currently equals Build.").closest("div") as HTMLElement;
    expect(within(banner).getByText("gpt-5.4")).toBeDefined();
    expect(screen.getByText("conflict")).toBeDefined();
  });

  it("shows NoAccessState for a non-admin", () => {
    mockUseMe.mockReturnValue({
      data: { email: "m@axelerant.com", is_admin: false }, isLoading: false, isError: false,
    } as unknown as ReturnType<typeof useMe>);
    render(<ModelsPage />);
    expect(screen.queryByLabelText("Chat model")).toBeNull();
  });
});
