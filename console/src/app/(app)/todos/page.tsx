"use client";

import { useState, type KeyboardEvent } from "react";
import { Info, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/common/states";
import {
  useClearDoneTodos, useCreateTodo, useDeleteTodo, useTodos, useToggleTodo, type Todo,
} from "@/lib/use-todos";

function TodoRow({ todo }: { todo: Todo }) {
  const toggle = useToggleTodo();
  const remove = useDeleteTodo();

  return (
    <div className="group flex items-center gap-3 border-b px-4 py-3 last:border-b-0">
      <input
        type="checkbox"
        checked={todo.done}
        onChange={(e) => toggle.mutate({ id: todo.id, done: e.target.checked })}
        aria-label={todo.done ? "Mark not done" : "Mark done"}
        className="size-4 accent-primary"
      />
      <span
        className={`min-w-0 flex-1 truncate text-sm ${todo.done ? "text-muted-foreground line-through" : ""}`}
      >
        {todo.text}
      </span>
      <button
        type="button"
        onClick={() => remove.mutate(todo.id)}
        aria-label="Delete todo"
        className="flex-none text-muted-foreground opacity-0 transition-opacity hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
      >
        <X className="size-4" />
      </button>
    </div>
  );
}

export default function TodosPage() {
  const { data: todos, isLoading, isError, refetch } = useTodos();
  const create = useCreateTodo();
  const clearDone = useClearDoneTodos();
  const [text, setText] = useState("");

  const hasDone = todos?.some((t) => t.done) ?? false;

  function submitAdd() {
    const trimmed = text.trim();
    if (!trimmed) return;
    create.mutate(trimmed, { onSuccess: () => setText("") });
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") submitAdd();
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-lg tracking-tight">Todos</h1>
        <p className="text-sm text-muted-foreground">
          Your quick working checklist — private to you, lives only here.
        </p>
      </div>

      <div className="flex gap-2 rounded-xl border bg-muted/40 px-3 py-2.5 text-sm">
        <Info className="mt-0.5 size-4 flex-none text-muted-foreground" />
        <p className="text-muted-foreground">
          Jot as you work. For follow-ups Bott should{" "}
          <b className="font-medium text-foreground">remember and remind you about</b>, use{" "}
          <b className="font-medium text-foreground">Action items</b> instead — those sync to Slack.
        </p>
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Add a todo… press Enter"
          aria-label="Add a todo"
          className="w-full rounded-md border bg-background px-2.5 py-1.5 text-sm"
        />
        <Button onClick={submitAdd} disabled={create.isPending || !text.trim()}>Add</Button>
      </div>

      <div className="rounded-xl border bg-card shadow-sm">
        {isLoading && <LoadingState />}
        {isError && <ErrorState message="Couldn't load — try refreshing the page." onRetry={() => refetch()} />}
        {!isLoading && !isError && !todos?.length && (
          <EmptyState title="Nothing here yet" message="Add a todo above to get started." />
        )}
        {todos?.map((todo) => <TodoRow key={todo.id} todo={todo} />)}
      </div>

      {hasDone && (
        <div className="flex justify-end">
          <Button variant="outline" size="sm" onClick={() => clearDone.mutate()} disabled={clearDone.isPending}>
            Clear completed
          </Button>
        </div>
      )}
    </div>
  );
}
