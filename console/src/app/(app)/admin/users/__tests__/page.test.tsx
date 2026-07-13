import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/use-users", async () => {
  const actual = await vi.importActual<typeof import("@/lib/use-users")>("@/lib/use-users");
  return {
    ...actual,
    useUsers: vi.fn(),
    useSetRole: vi.fn(),
    useInvite: vi.fn(),
    useRevokeInvite: vi.fn(),
  };
});

import { useInvite, useRevokeInvite, useSetRole, useUsers } from "@/lib/use-users";
import UsersPage from "../page";

const mockUseUsers = vi.mocked(useUsers);
const mockUseSetRole = vi.mocked(useSetRole);
const mockUseInvite = vi.mocked(useInvite);
const mockUseRevokeInvite = vi.mocked(useRevokeInvite);

let setRoleMutate: ReturnType<typeof vi.fn>;
let inviteMutate: ReturnType<typeof vi.fn>;
let revokeMutate: ReturnType<typeof vi.fn>;

const USERS = [
  { email: "seeded@axelerant.com", role: "admin" as const, locked: true, invited: false, last_active: Date.now() / 1000 },
  { email: "promoted@axelerant.com", role: "admin" as const, locked: false, invited: false, last_active: Date.now() / 1000 },
  { email: "member@axelerant.com", role: "member" as const, locked: false, invited: false, last_active: Date.now() / 1000 },
  { email: "pending@axelerant.com", role: "member" as const, locked: false, invited: true, last_active: null },
];

beforeEach(() => {
  setRoleMutate = vi.fn();
  inviteMutate = vi.fn((_vars, opts) => opts?.onSuccess?.());
  revokeMutate = vi.fn();

  mockUseUsers.mockReturnValue({
    data: USERS, isLoading: false, isError: false, refetch: vi.fn(),
  } as unknown as ReturnType<typeof useUsers>);
  mockUseSetRole.mockReturnValue({ mutate: setRoleMutate, isPending: false } as unknown as ReturnType<typeof useSetRole>);
  mockUseInvite.mockReturnValue({ mutate: inviteMutate, isPending: false } as unknown as ReturnType<typeof useInvite>);
  mockUseRevokeInvite.mockReturnValue({ mutate: revokeMutate, isPending: false } as unknown as ReturnType<typeof useRevokeInvite>);
});

describe("UsersPage", () => {
  it("renders every user row with its email", () => {
    render(<UsersPage />);
    for (const u of USERS) expect(screen.getByText(u.email)).toBeDefined();
  });

  it("shows a disabled Locked button with a tooltip for an env-seeded admin", () => {
    render(<UsersPage />);
    const button = screen.getByText("Locked").closest("button") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.title).toContain("lockout protection");
  });

  it("shows Remove admin for a KV-promoted (unlocked) admin and demotes on click", () => {
    render(<UsersPage />);
    const row = screen.getByText("promoted@axelerant.com").closest("div.flex") as HTMLElement;
    const button = row.querySelector("button") as HTMLButtonElement;
    fireEvent.click(button);
    expect(setRoleMutate).toHaveBeenCalledWith({ email: "promoted@axelerant.com", role: "member" });
  });

  it("shows Make admin for a member and promotes on click", () => {
    render(<UsersPage />);
    const row = screen.getByText("member@axelerant.com").closest("div.flex") as HTMLElement;
    const button = row.querySelector("button") as HTMLButtonElement;
    expect(button.textContent).toBe("Make admin");
    fireEvent.click(button);
    expect(setRoleMutate).toHaveBeenCalledWith({ email: "member@axelerant.com", role: "admin" });
  });

  it("shows Revoke for an invited (never-signed-in) row and revokes on click", () => {
    render(<UsersPage />);
    const row = screen.getByText("pending@axelerant.com").closest("div.flex") as HTMLElement;
    const button = row.querySelector("button") as HTMLButtonElement;
    expect(button.textContent).toBe("Revoke");
    fireEvent.click(button);
    expect(revokeMutate).toHaveBeenCalledWith("pending@axelerant.com");
  });

  it("shows the Invited badge and meta copy for a pending invite", () => {
    render(<UsersPage />);
    expect(screen.getByText("Invited")).toBeDefined();
    expect(screen.getByText(/hasn't signed in yet/)).toBeDefined();
  });

  it("opens the invite drawer, fills the form, and sends the invite", () => {
    render(<UsersPage />);
    fireEvent.click(screen.getByText("Invite user"));
    const emailInput = screen.getByPlaceholderText("name@axelerant.com") as HTMLInputElement;
    fireEvent.change(emailInput, { target: { value: "new@axelerant.com" } });
    fireEvent.click(screen.getByText("Send invite"));
    expect(inviteMutate).toHaveBeenCalledWith(
      { email: "new@axelerant.com", role: "member" },
      expect.anything(),
    );
  });

  it("does not allow sending an invite with a blank email", () => {
    render(<UsersPage />);
    fireEvent.click(screen.getByText("Invite user"));
    expect((screen.getByText("Send invite") as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows an empty state when there are no users", () => {
    mockUseUsers.mockReturnValue({
      data: [], isLoading: false, isError: false, refetch: vi.fn(),
    } as unknown as ReturnType<typeof useUsers>);
    render(<UsersPage />);
    expect(screen.getByText("Nobody yet")).toBeDefined();
  });
});
