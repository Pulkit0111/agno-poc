import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";

vi.mock("@/lib/use-connectors", async () => {
  const actual = await vi.importActual<typeof import("@/lib/use-connectors")>("@/lib/use-connectors");
  return {
    ...actual,
    useConnectors: vi.fn(),
    useTestConnector: vi.fn(),
    useAddConnector: vi.fn(),
    useRemoveConnector: vi.fn(),
  };
});
vi.mock("@/lib/use-me", async () => {
  const actual = await vi.importActual<typeof import("@/lib/use-me")>("@/lib/use-me");
  return { ...actual, useMe: vi.fn() };
});

import {
  useAddConnector, useConnectors, useRemoveConnector, useTestConnector,
} from "@/lib/use-connectors";
import { useMe } from "@/lib/use-me";
import ConnectorsPage from "../page";

const mockUseConnectors = vi.mocked(useConnectors);
const mockUseTestConnector = vi.mocked(useTestConnector);
const mockUseAddConnector = vi.mocked(useAddConnector);
const mockUseRemoveConnector = vi.mocked(useRemoveConnector);
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
let addMutate: ReturnType<typeof vi.fn>;
let addReset: ReturnType<typeof vi.fn>;
let removeMutate: ReturnType<typeof vi.fn>;

beforeEach(() => {
  testMutate = vi.fn();
  testReset = vi.fn();
  addMutate = vi.fn();
  addReset = vi.fn();
  removeMutate = vi.fn();
  mockUseConnectors.mockReturnValue({
    data: CONNECTORS, isLoading: false, isError: false, refetch: vi.fn(),
  } as unknown as ReturnType<typeof useConnectors>);
  mockUseTestConnector.mockReturnValue({
    mutate: testMutate, reset: testReset, isPending: false, data: undefined,
  } as unknown as ReturnType<typeof useTestConnector>);
  mockUseAddConnector.mockReturnValue({
    mutate: addMutate, reset: addReset, isPending: false, error: null,
  } as unknown as ReturnType<typeof useAddConnector>);
  mockUseRemoveConnector.mockReturnValue({
    mutate: removeMutate, isPending: false,
  } as unknown as ReturnType<typeof useRemoveConnector>);
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

  it("shows the Add connector button for an admin and opens the type picker", () => {
    render(<ConnectorsPage />);
    fireEvent.click(screen.getByText("Add connector"));
    expect(screen.getByText("GitHub (org app)")).toBeDefined();
    expect(screen.getByText("Sentry (second org)")).toBeDefined();
    expect(screen.getByText("Custom HTTP API")).toBeDefined();
  });

  it("hides the Add connector button for a member", () => {
    mockUseMe.mockReturnValue({
      data: { email: "m@axelerant.com", is_admin: false }, isLoading: false, isError: false,
    } as unknown as ReturnType<typeof useMe>);
    render(<ConnectorsPage />);
    expect(screen.queryByText("Add connector")).toBeNull();
  });

  it("submits a custom HTTP API connector with the typed fields", () => {
    render(<ConnectorsPage />);
    fireEvent.click(screen.getByText("Add connector"));
    fireEvent.click(screen.getByText("Custom HTTP API"));
    fireEvent.change(screen.getByPlaceholderText("Name/slug"), { target: { value: "acme" } });
    fireEvent.change(screen.getByPlaceholderText("Base URL"), { target: { value: "https://acme.example.com" } });
    fireEvent.click(screen.getByText("Connect & test"));
    expect(addMutate).toHaveBeenCalledWith(
      { type: "http_api", fields: { name: "acme", base_url: "https://acme.example.com", header_name: "", header_value: "" } },
      expect.anything(),
    );
  });

  it("disables Connect & test until required fields are filled", () => {
    render(<ConnectorsPage />);
    fireEvent.click(screen.getByText("Add connector"));
    fireEvent.click(screen.getByText("Sentry (second org)"));
    expect((screen.getByText("Connect & test") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByPlaceholderText("Org slug"), { target: { value: "acme" } });
    fireEvent.change(screen.getByPlaceholderText("Auth token"), { target: { value: "tok" } });
    expect((screen.getByText("Connect & test") as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows the 422 probe-failure message inline in the drawer", () => {
    mockUseAddConnector.mockReturnValue({
      mutate: addMutate, reset: addReset, isPending: false,
      error: new ApiError(422, "probe_failed", "Couldn't reach acme (401 unauthorized)."),
    } as unknown as ReturnType<typeof useAddConnector>);
    render(<ConnectorsPage />);
    fireEvent.click(screen.getByText("Add connector"));
    fireEvent.click(screen.getByText("Custom HTTP API"));
    expect(screen.getByText("Couldn't reach acme (401 unauthorized).")).toBeDefined();
  });

  it("shows a Remove button only for a store-backed (non-static) connector, for an admin", () => {
    mockUseConnectors.mockReturnValue({
      data: [...CONNECTORS, { name: "sentry-secondorg", ok: true, on: "Added from the console", off: "", fix: [] }],
      isLoading: false, isError: false, refetch: vi.fn(),
    } as unknown as ReturnType<typeof useConnectors>);
    render(<ConnectorsPage />);
    expect(screen.getAllByText("Remove").length).toBe(1);
  });

  it("confirms before removing a store-backed connector", () => {
    mockUseConnectors.mockReturnValue({
      data: [...CONNECTORS, { name: "sentry-secondorg", ok: true, on: "Added from the console", off: "", fix: [] }],
      isLoading: false, isError: false, refetch: vi.fn(),
    } as unknown as ReturnType<typeof useConnectors>);
    render(<ConnectorsPage />);
    fireEvent.click(screen.getByText("Remove"));
    expect(screen.getByText("Remove this connector?")).toBeDefined();
    // Confirm the dialog's own action (the second "Remove" in the DOM: card button + dialog confirm).
    const removeButtons = screen.getAllByText("Remove");
    fireEvent.click(removeButtons[removeButtons.length - 1]);
    expect(removeMutate).toHaveBeenCalledWith("sentry-secondorg");
  });

  it("hides Remove for a member even for a store-backed connector", () => {
    mockUseConnectors.mockReturnValue({
      data: [...CONNECTORS, { name: "sentry-secondorg", ok: true, on: "Added from the console", off: "", fix: [] }],
      isLoading: false, isError: false, refetch: vi.fn(),
    } as unknown as ReturnType<typeof useConnectors>);
    mockUseMe.mockReturnValue({
      data: { email: "m@axelerant.com", is_admin: false }, isLoading: false, isError: false,
    } as unknown as ReturnType<typeof useMe>);
    render(<ConnectorsPage />);
    expect(screen.queryByText("Remove")).toBeNull();
  });
});
