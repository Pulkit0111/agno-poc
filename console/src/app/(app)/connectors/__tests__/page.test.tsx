import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/use-connectors", async () => {
  const actual = await vi.importActual<typeof import("@/lib/use-connectors")>("@/lib/use-connectors");
  return { ...actual, useConnectors: vi.fn(), useTestConnector: vi.fn() };
});
vi.mock("@/lib/use-me", async () => {
  const actual = await vi.importActual<typeof import("@/lib/use-me")>("@/lib/use-me");
  return { ...actual, useMe: vi.fn() };
});

import { useConnectors, useTestConnector } from "@/lib/use-connectors";
import { useMe } from "@/lib/use-me";
import ConnectorsPage from "../page";

const mockUseConnectors = vi.mocked(useConnectors);
const mockUseTestConnector = vi.mocked(useTestConnector);
const mockUseMe = vi.mocked(useMe);

const CONNECTORS = [
  {
    name: "Jira", ok: false, on: "read-only · org", off: "set JIRA_BASE_URL + JIRA_EMAIL + JIRA_API_TOKEN",
    fix: ["Set JIRA_BASE_URL to your site URL.", "Set JIRA_EMAIL + JIRA_API_TOKEN.", "Restart Bott."],
  },
  { name: "Slack", ok: true, on: "connected", off: "set SLACK_BOT_TOKEN + SLACK_SIGNING_SECRET", fix: ["step"] },
  { name: "Spin", ok: false, on: "page publishing", off: "set SPIN_API_TOKEN", fix: ["Set SPIN_API_TOKEN."] },
];

let testMutate: ReturnType<typeof vi.fn>;
let testReset: ReturnType<typeof vi.fn>;

beforeEach(() => {
  testMutate = vi.fn();
  testReset = vi.fn();
  mockUseConnectors.mockReturnValue({
    data: CONNECTORS, isLoading: false, isError: false, refetch: vi.fn(),
  } as unknown as ReturnType<typeof useConnectors>);
  mockUseTestConnector.mockReturnValue({
    mutate: testMutate, reset: testReset, isPending: false, data: undefined,
  } as unknown as ReturnType<typeof useTestConnector>);
  mockUseMe.mockReturnValue({
    data: { email: "admin@axelerant.com", is_admin: true }, isLoading: false, isError: false,
  } as unknown as ReturnType<typeof useMe>);
});

describe("ConnectorsPage", () => {
  it("renders every connector card", () => {
    render(<ConnectorsPage />);
    for (const c of CONNECTORS) expect(screen.getByText(c.name)).toBeDefined();
  });

  it("shows a Fix setup button for a broken connector (admin) and opens the drawer", () => {
    render(<ConnectorsPage />);
    const buttons = screen.getAllByText("Fix setup");
    expect(buttons.length).toBeGreaterThan(0);
    fireEvent.click(buttons[0]);
    expect(screen.getByText("Jira — fix setup")).toBeDefined();
    expect(screen.getByText("Set JIRA_BASE_URL to your site URL.")).toBeDefined();
  });

  it("shows a Test button for a connected, testable connector (Slack) and triggers the probe", () => {
    render(<ConnectorsPage />);
    const testButtons = screen.getAllByText("Test");
    expect(testButtons.length).toBe(1); // only Slack is ok + testable here
    fireEvent.click(testButtons[0]);
    expect(testMutate).toHaveBeenCalledWith("Slack");
  });

  it("does not show a Test connection button for a connector without a live probe (Spin)", () => {
    render(<ConnectorsPage />);
    fireEvent.click(screen.getAllByText("Fix setup")[1]); // Spin's Fix setup button
    expect(screen.getByText("Spin — fix setup")).toBeDefined();
    expect(screen.queryByText("Test connection")).toBeNull();
  });

  it("shows the Test connection button in the drawer for a testable connector and calls the probe", () => {
    render(<ConnectorsPage />);
    fireEvent.click(screen.getAllByText("Fix setup")[0]); // Jira
    const testConnectionButton = screen.getByText("Test connection");
    fireEvent.click(testConnectionButton);
    expect(testMutate).toHaveBeenCalledWith("Jira");
  });

  it("shows the probe result inline in the drawer", () => {
    mockUseTestConnector.mockReturnValue({
      mutate: testMutate, reset: testReset, isPending: false,
      data: { ok: false, message: "Couldn't reach jira (401 unauthorized)." },
    } as unknown as ReturnType<typeof useTestConnector>);
    render(<ConnectorsPage />);
    fireEvent.click(screen.getAllByText("Fix setup")[0]);
    expect(screen.getByText("Couldn't reach jira (401 unauthorized).")).toBeDefined();
  });

  it("hides Fix setup and Test buttons for a member (non-admin)", () => {
    mockUseMe.mockReturnValue({
      data: { email: "m@axelerant.com", is_admin: false }, isLoading: false, isError: false,
    } as unknown as ReturnType<typeof useMe>);
    render(<ConnectorsPage />);
    expect(screen.queryByText("Fix setup")).toBeNull();
    expect(screen.queryByText("Test")).toBeNull();
    expect(screen.getAllByText("Ask an admin to reconnect this.").length).toBe(2);
  });
});
