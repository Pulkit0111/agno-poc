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
// provider/model pickers, so stub it out to a simple marker.
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
    { name: "openrouter", usable: true, hint: "OpenRouter key present", models: [] },
    { name: "bedrock", usable: false, hint: "Add AWS credentials to list and use Bedrock models", models: [] },
  ],
  codex_usage: null,
  active: {
    provider: "codex", chat: "gpt-5.5", build: "gpt-5.5-codex", review: "gpt-5.4",
    providers_by_role: { chat: "codex", build: "codex", review: "codex" },
  },
  catalogs: {
    codex: ["gpt-5.5", "gpt-5.5-codex", "gpt-5.4"],
    openrouter: ["anthropic/claude-opus-4.8", "openai/gpt-5.5"],
    bedrock: [],
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
  it("renders the three jobs, each with a provider dropdown and a model dropdown", () => {
    render(<ModelsPage />);
    for (const label of ["Chat", "Build", "Review"]) {
      expect(screen.getByText(label)).toBeDefined();
    }
    expect(screen.getByLabelText("Chat provider")).toBeDefined();
    expect(screen.getByLabelText("Chat model")).toBeDefined();
    expect(screen.getByLabelText("Build provider")).toBeDefined();
    expect(screen.getByLabelText("Build model")).toBeDefined();
    expect(screen.getByLabelText("Review provider")).toBeDefined();
    expect(screen.getByLabelText("Review model")).toBeDefined();
  });

  it("replaces the old 'Codex is the only provider' copy", () => {
    render(<ModelsPage />);
    expect(screen.getByText("Pick which provider and model handles each job")).toBeDefined();
    expect(screen.queryByText(/Bott's only model provider/i)).toBeNull();
  });

  it("only offers Bedrock as a provider option when it's usable", () => {
    render(<ModelsPage />);
    const select = screen.getByLabelText("Chat provider") as HTMLSelectElement;
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Codex", "OpenRouter"]);
  });

  it("offers Bedrock once it's usable", () => {
    setData({
      providers: BASE_DATA.providers.map((p) => (p.name === "bedrock" ? { ...p, usable: true } : p)),
    });
    render(<ModelsPage />);
    const select = screen.getByLabelText("Chat provider") as HTMLSelectElement;
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Codex", "OpenRouter", "Bedrock"]);
  });

  it("shows the model dropdown fed by the codex catalog by default", () => {
    render(<ModelsPage />);
    const select = screen.getByLabelText("Chat model") as HTMLSelectElement;
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["gpt-5.5", "gpt-5.5-codex", "gpt-5.4"]);
    expect(select.value).toBe("gpt-5.5");
  });

  it("selecting OpenRouter for Chat's provider fires the provider mutation and swaps the model catalog", () => {
    render(<ModelsPage />);
    const providerSelect = screen.getByLabelText("Chat provider") as HTMLSelectElement;
    fireEvent.change(providerSelect, { target: { value: "openrouter" } });

    expect(mutate).toHaveBeenCalledWith({ key: "model.provider.chat", value: "openrouter" });
    // Auto-defaults + persists the first model in the new provider's catalog so the
    // dropdown is never left empty/mismatched.
    expect(mutate).toHaveBeenCalledWith({ key: "model.chat", value: "anthropic/claude-opus-4.8" });

    const modelSelect = screen.getByLabelText("Chat model") as HTMLSelectElement;
    const options = within(modelSelect).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["anthropic/claude-opus-4.8", "openai/gpt-5.5"]);
    expect(modelSelect.value).toBe("anthropic/claude-opus-4.8");
  });

  it("changing the model dropdown fires the model mutation", () => {
    render(<ModelsPage />);
    const modelSelect = screen.getByLabelText("Chat model") as HTMLSelectElement;
    fireEvent.change(modelSelect, { target: { value: "gpt-5.4" } });
    expect(mutate).toHaveBeenCalledWith({ key: "model.chat", value: "gpt-5.4" });
  });

  it("shows an empty-catalog hint instead of a model dropdown when the provider has no key", () => {
    setData({
      active: {
        ...BASE_DATA.active,
        providers_by_role: { ...BASE_DATA.active.providers_by_role, chat: "bedrock" },
      },
    });
    render(<ModelsPage />);
    expect(screen.queryByLabelText("Chat model")).toBeNull();
    expect(screen.getByText("Add AWS credentials to list and use Bedrock models")).toBeDefined();
  });

  it("keeps the provider select on the active provider even when it's now unusable (no coercion to Codex)", () => {
    // Bedrock is the active provider for Chat but is NOT usable (no AWS creds) — the
    // dropdown must still show "bedrock", not silently coerce to the first option.
    setData({
      active: {
        ...BASE_DATA.active,
        providers_by_role: { ...BASE_DATA.active.providers_by_role, chat: "bedrock" },
      },
    });
    render(<ModelsPage />);
    const select = screen.getByLabelText("Chat provider") as HTMLSelectElement;
    expect(select.value).toBe("bedrock");
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Codex", "OpenRouter", "Bedrock (unavailable)"]);
  });

  it("shows OpenRouter connected when usable", () => {
    render(<ModelsPage />);
    expect(screen.getByText("OpenRouter connected ✓")).toBeDefined();
  });

  it("shows the add-key hint when OpenRouter isn't usable", () => {
    setData({
      providers: BASE_DATA.providers.map((p) => (p.name === "openrouter" ? { ...p, usable: false } : p)),
    });
    render(<ModelsPage />);
    expect(screen.getByText("OpenRouter: add OPENROUTER_API_KEY to .env to use it")).toBeDefined();
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
    expect(screen.queryByLabelText("Chat provider")).toBeNull();
  });
});
