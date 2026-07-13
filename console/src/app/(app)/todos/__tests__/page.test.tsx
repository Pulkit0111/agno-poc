import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/use-todos", async () => {
  const actual = await vi.importActual<typeof import("@/lib/use-todos")>("@/lib/use-todos");
  return {
    ...actual,
    useTodos: vi.fn(),
    useCreateTodo: vi.fn(),
    useToggleTodo: vi.fn(),
    useDeleteTodo: vi.fn(),
    useClearDoneTodos: vi.fn(),
  };
});

import {
  useClearDoneTodos, useCreateTodo, useDeleteTodo, useTodos, useToggleTodo,
} from "@/lib/use-todos";
import TodosPage from "../page";

const mockUseTodos = vi.mocked(useTodos);
const mockUseCreateTodo = vi.mocked(useCreateTodo);
const mockUseToggleTodo = vi.mocked(useToggleTodo);
const mockUseDeleteTodo = vi.mocked(useDeleteTodo);
const mockUseClearDoneTodos = vi.mocked(useClearDoneTodos);

let createMutate: ReturnType<typeof vi.fn>;
let toggleMutate: ReturnType<typeof vi.fn>;
let deleteMutate: ReturnType<typeof vi.fn>;
let clearDoneMutate: ReturnType<typeof vi.fn>;

const TODOS = [
  { id: 1, text: "Reply to Ankit's comment", done: false, created: Date.now() / 1000 },
  { id: 2, text: "Book meeting room", done: true, created: Date.now() / 1000 },
];

beforeEach(() => {
  createMutate = vi.fn();
  toggleMutate = vi.fn();
  deleteMutate = vi.fn();
  clearDoneMutate = vi.fn();

  mockUseTodos.mockReturnValue({
    data: TODOS, isLoading: false, isError: false, refetch: vi.fn(),
  } as unknown as ReturnType<typeof useTodos>);
  mockUseCreateTodo.mockReturnValue({ mutate: createMutate, isPending: false } as unknown as ReturnType<typeof useCreateTodo>);
  mockUseToggleTodo.mockReturnValue({ mutate: toggleMutate, isPending: false } as unknown as ReturnType<typeof useToggleTodo>);
  mockUseDeleteTodo.mockReturnValue({ mutate: deleteMutate, isPending: false } as unknown as ReturnType<typeof useDeleteTodo>);
  mockUseClearDoneTodos.mockReturnValue({ mutate: clearDoneMutate, isPending: false } as unknown as ReturnType<typeof useClearDoneTodos>);
});

describe("TodosPage", () => {
  it("renders the checklist with done items struck through", () => {
    render(<TodosPage />);
    expect(screen.getByText("Reply to Ankit's comment")).toBeDefined();
    const done = screen.getByText("Book meeting room");
    expect(done.className).toContain("line-through");
  });

  it("adds a todo on Enter and clears the input", () => {
    render(<TodosPage />);
    const input = screen.getByPlaceholderText("Add a todo… press Enter") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "New todo" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(createMutate).toHaveBeenCalledWith("New todo", expect.anything());
  });

  it("adds a todo via the Add button", () => {
    render(<TodosPage />);
    const input = screen.getByPlaceholderText("Add a todo… press Enter");
    fireEvent.change(input, { target: { value: "Another todo" } });
    fireEvent.click(screen.getByText("Add"));
    expect(createMutate).toHaveBeenCalledWith("Another todo", expect.anything());
  });

  it("does not submit a blank todo", () => {
    render(<TodosPage />);
    fireEvent.click(screen.getByText("Add"));
    expect(createMutate).not.toHaveBeenCalled();
  });

  it("toggles a todo's done state via its checkbox", () => {
    render(<TodosPage />);
    const checkboxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    fireEvent.click(checkboxes[0]);
    expect(toggleMutate).toHaveBeenCalledWith({ id: 1, done: true });
  });

  it("deletes a todo via its delete button", () => {
    render(<TodosPage />);
    const deleteButtons = screen.getAllByLabelText("Delete todo");
    fireEvent.click(deleteButtons[0]);
    expect(deleteMutate).toHaveBeenCalledWith(1);
  });

  it("shows Clear completed when a todo is done and fires the mutation", () => {
    render(<TodosPage />);
    const button = screen.getByText("Clear completed");
    fireEvent.click(button);
    expect(clearDoneMutate).toHaveBeenCalled();
  });

  it("hides Clear completed when nothing is done", () => {
    mockUseTodos.mockReturnValue({
      data: [TODOS[0]], isLoading: false, isError: false, refetch: vi.fn(),
    } as unknown as ReturnType<typeof useTodos>);
    render(<TodosPage />);
    expect(screen.queryByText("Clear completed")).toBeNull();
  });

  it("shows an empty state when there are no todos", () => {
    mockUseTodos.mockReturnValue({
      data: [], isLoading: false, isError: false, refetch: vi.fn(),
    } as unknown as ReturnType<typeof useTodos>);
    render(<TodosPage />);
    expect(screen.getByText("Nothing here yet")).toBeDefined();
  });
});
