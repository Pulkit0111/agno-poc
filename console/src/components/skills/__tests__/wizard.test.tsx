import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));

vi.mock("@/lib/use-skills", async () => {
  const actual = await vi.importActual<typeof import("@/lib/use-skills")>("@/lib/use-skills");
  return { ...actual, useDraftSkill: vi.fn(), useSaveSkill: vi.fn() };
});

import { useDraftSkill, useSaveSkill } from "@/lib/use-skills";
import { SkillWizard } from "../skill-wizard";

const mockUseDraftSkill = vi.mocked(useDraftSkill);
const mockUseSaveSkill = vi.mocked(useSaveSkill);

let draftMutate: ReturnType<typeof vi.fn>;
let saveMutate: ReturnType<typeof vi.fn>;

const SAMPLE_DRAFT = {
  slug: "pr-nudge",
  name: "pr-nudge",
  description: "Nudges reviewers about stale PRs.",
  content: "# pr-nudge\n\n**When to use:** stale PRs.\n\n## Steps\n1. List them.\n",
};

beforeEach(() => {
  pushMock.mockReset();
  draftMutate = vi.fn();
  saveMutate = vi.fn();
  mockUseDraftSkill.mockReturnValue({ mutate: draftMutate, isPending: false, isError: false } as unknown as ReturnType<typeof useDraftSkill>);
  mockUseSaveSkill.mockReturnValue({ mutate: saveMutate, isPending: false } as unknown as ReturnType<typeof useSaveSkill>);
});

describe("SkillWizard", () => {
  it("keeps 'Draft it for me' disabled until both fields are filled", () => {
    render(<SkillWizard />);
    const draftButton = screen.getByText("Draft it for me") as HTMLButtonElement;
    expect(draftButton.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("What should this skill do?"), { target: { value: "Nudge stale PRs" } });
    expect(draftButton.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("When should Bott reach for it?"), { target: { value: "someone asks about stale PRs" } });
    expect(draftButton.disabled).toBe(false);
  });

  it("walks step 1 -> drafting -> preview and calls the draft mutation with what/when", () => {
    render(<SkillWizard />);
    fireEvent.change(screen.getByLabelText("What should this skill do?"), { target: { value: "Nudge stale PRs" } });
    fireEvent.change(screen.getByLabelText("When should Bott reach for it?"), { target: { value: "stale PRs" } });
    fireEvent.click(screen.getByText("Draft it for me"));

    expect(draftMutate).toHaveBeenCalledWith(
      { what: "Nudge stale PRs", when: "stale PRs", feedback: "" },
      expect.anything(),
    );
    expect(screen.getByText("Bott is drafting your skill…")).toBeDefined();

    // Resolve the draft mutation the way the real hook would (via the passed onSuccess).
    const [, opts] = draftMutate.mock.calls[0];
    act(() => opts.onSuccess(SAMPLE_DRAFT));

    expect(screen.getByRole("heading", { level: 1, name: "pr-nudge" })).toBeDefined();
    expect(screen.getByText("Save skill")).toBeDefined();
  });

  it("shows an ErrorState with retry when the draft mutation is in an error state", () => {
    mockUseDraftSkill.mockReturnValue({ mutate: draftMutate, isPending: false, isError: true } as unknown as ReturnType<typeof useDraftSkill>);
    render(<SkillWizard />);
    fireEvent.change(screen.getByLabelText("What should this skill do?"), { target: { value: "Nudge stale PRs" } });
    fireEvent.change(screen.getByLabelText("When should Bott reach for it?"), { target: { value: "stale PRs" } });
    fireEvent.click(screen.getByText("Draft it for me"));

    expect(screen.getByText("Couldn't draft that skill — try again.")).toBeDefined();
    const retryButton = screen.getByText("Retry");
    expect(retryButton).toBeDefined();

    // Retry calls the mutation again with the same what/when.
    fireEvent.click(retryButton);
    expect(draftMutate).toHaveBeenCalledWith(
      { what: "Nudge stale PRs", when: "stale PRs", feedback: "" },
      expect.anything(),
    );
  });

  it("refining replaces the preview without navigating away", () => {
    render(<SkillWizard />);
    fireEvent.change(screen.getByLabelText("What should this skill do?"), { target: { value: "Nudge stale PRs" } });
    fireEvent.change(screen.getByLabelText("When should Bott reach for it?"), { target: { value: "stale PRs" } });
    fireEvent.click(screen.getByText("Draft it for me"));
    act(() => draftMutate.mock.calls[0][1].onSuccess(SAMPLE_DRAFT));

    fireEvent.change(screen.getByLabelText("Ask for a change"), { target: { value: "only weekdays" } });
    fireEvent.click(screen.getByText("Refine"));

    expect(draftMutate).toHaveBeenLastCalledWith(
      { what: "Nudge stale PRs", when: "stale PRs", feedback: "only weekdays" },
      expect.anything(),
    );

    const refined = { ...SAMPLE_DRAFT, content: "# pr-nudge\n\nOnly on weekdays now.\n" };
    act(() => draftMutate.mock.calls[1][1].onSuccess(refined));

    expect(screen.getByText("Only on weekdays now.")).toBeDefined();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("Save skill saves the draft and navigates to the new skill's detail page", () => {
    render(<SkillWizard />);
    fireEvent.change(screen.getByLabelText("What should this skill do?"), { target: { value: "Nudge stale PRs" } });
    fireEvent.change(screen.getByLabelText("When should Bott reach for it?"), { target: { value: "stale PRs" } });
    fireEvent.click(screen.getByText("Draft it for me"));
    act(() => draftMutate.mock.calls[0][1].onSuccess(SAMPLE_DRAFT));

    fireEvent.click(screen.getByText("Save skill"));
    expect(saveMutate).toHaveBeenCalledWith(SAMPLE_DRAFT, expect.anything());

    const [, opts] = saveMutate.mock.calls[0];
    act(() => opts.onSuccess({ slug: "pr-nudge" }));
    expect(pushMock).toHaveBeenCalledWith("/skills/pr-nudge");
  });

  it("Discard leaves the wizard without saving", () => {
    render(<SkillWizard />);
    fireEvent.change(screen.getByLabelText("What should this skill do?"), { target: { value: "Nudge stale PRs" } });
    fireEvent.change(screen.getByLabelText("When should Bott reach for it?"), { target: { value: "stale PRs" } });
    fireEvent.click(screen.getByText("Draft it for me"));
    act(() => draftMutate.mock.calls[0][1].onSuccess(SAMPLE_DRAFT));

    fireEvent.click(screen.getByText("Discard"));
    expect(saveMutate).not.toHaveBeenCalled();
    expect(pushMock).toHaveBeenCalledWith("/skills");
  });
});
