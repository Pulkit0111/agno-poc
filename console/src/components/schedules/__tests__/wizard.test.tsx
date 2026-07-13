import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/use-schedules", async () => {
  const actual = await vi.importActual<typeof import("@/lib/use-schedules")>("@/lib/use-schedules");
  return { ...actual, useCreateSchedule: vi.fn(), useSchedulePreview: vi.fn() };
});

import { useCreateSchedule, useSchedulePreview } from "@/lib/use-schedules";
import { ScheduleWizard } from "../schedule-wizard";

const mockUseCreateSchedule = vi.mocked(useCreateSchedule);
const mockUseSchedulePreview = vi.mocked(useSchedulePreview);

let createMutate: ReturnType<typeof vi.fn>;
let previewMutate: ReturnType<typeof vi.fn>;

beforeEach(() => {
  createMutate = vi.fn();
  previewMutate = vi.fn();
  mockUseCreateSchedule.mockReturnValue({ mutate: createMutate, isPending: false } as unknown as ReturnType<typeof useCreateSchedule>);
  mockUseSchedulePreview.mockReturnValue({ mutate: previewMutate, data: undefined, isPending: false } as unknown as ReturnType<typeof useSchedulePreview>);
});

describe("ScheduleWizard", () => {
  it("walks kind -> details -> cadence for delivery and submits the right payload", () => {
    render(<ScheduleWizard open onOpenChange={() => {}} />);

    fireEvent.click(screen.getByText("Delivery digest"));
    fireEvent.click(screen.getByText("Next"));

    fireEvent.change(screen.getByLabelText("Engagement"), { target: { value: "acme-commerce" } });
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "#acme-commerce" } });
    fireEvent.click(screen.getByText("Next"));

    // Entering the cadence step previews the default frequency automatically.
    expect(previewMutate).toHaveBeenCalledWith(expect.objectContaining({ kind: "delivery", time: "09:00" }));

    fireEvent.click(screen.getByText("Weekdays"));
    expect(previewMutate).toHaveBeenCalledWith({ kind: "delivery", frequency: "weekdays", time: "09:00" });

    fireEvent.click(screen.getByText("Create schedule"));
    expect(createMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "delivery",
        channel: "#acme-commerce",
        engagement: "acme-commerce",
        frequency: "weekdays",
        time: "09:00",
      }),
      expect.anything(),
    );
  });

  it("keeps parity with the old form: sprint has no cadence choice (fixed weekly)", () => {
    render(<ScheduleWizard open onOpenChange={() => {}} />);

    // Sprint report is the first/default kind card.
    fireEvent.click(screen.getByText("Next"));
    fireEvent.change(screen.getByLabelText("Engagement"), { target: { value: "acme-commerce" } });
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "#acme-commerce" } });
    fireEvent.click(screen.getByText("Next"));

    expect(screen.queryByText("Weekly")).toBeNull();
    expect(previewMutate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Create schedule"));
    expect(createMutate).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "sprint", channel: "#acme-commerce", engagement: "acme-commerce", frequency: undefined }),
      expect.anything(),
    );
  });

  it("collects team + channel for a daily standup schedule", () => {
    render(<ScheduleWizard open onOpenChange={() => {}} />);

    fireEvent.click(screen.getByText("Daily standup"));
    fireEvent.click(screen.getByText("Next"));

    fireEvent.change(screen.getByLabelText("Team"), { target: { value: "Team Falcon" } });
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "#falcon-standup" } });
    fireEvent.click(screen.getByText("Next"));

    fireEvent.click(screen.getByText("Create schedule"));
    expect(createMutate).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "dsm", team: "Team Falcon", channel: "#falcon-standup", engagement: undefined }),
      expect.anything(),
    );
  });

  it("disables Next on the details step until required fields are filled", () => {
    render(<ScheduleWizard open onOpenChange={() => {}} />);
    fireEvent.click(screen.getByText("Security advisories"));
    fireEvent.click(screen.getByText("Next"));
    expect((screen.getByText("Next") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "#drupal-security" } });
    expect((screen.getByText("Next") as HTMLButtonElement).disabled).toBe(false);
  });

  it("supports going back a step without losing entered values", () => {
    render(<ScheduleWizard open onOpenChange={() => {}} />);
    fireEvent.click(screen.getByText("Security advisories"));
    fireEvent.click(screen.getByText("Next"));
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "#drupal-security" } });
    fireEvent.click(screen.getByText("Next"));
    fireEvent.click(screen.getByText("Back"));
    expect((screen.getByLabelText("Channel") as HTMLInputElement).value).toBe("#drupal-security");
  });
});
