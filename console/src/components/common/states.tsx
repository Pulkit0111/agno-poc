"use client";

import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { isForbidden } from "@/lib/api";

/** Skeleton list placeholder while a query is loading. */
export function LoadingState({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10" />
      ))}
    </div>
  );
}

/** Friendly centered empty state — formalizes the muted-text idiom used across pages. */
export function EmptyState({
  icon,
  title,
  message,
}: {
  icon?: ReactNode;
  title: string;
  message: string;
}) {
  return (
    <div className="flex flex-col items-center gap-1.5 px-4 py-10 text-center">
      {icon && (
        <div className="mb-1 text-muted-foreground [&_svg]:size-6">{icon}</div>
      )}
      <div className="text-sm font-medium text-foreground">{title}</div>
      <p className="max-w-sm text-sm text-muted-foreground">{message}</p>
    </div>
  );
}

/** Load-failure state with an optional Retry button. */
export function ErrorState({
  onRetry,
  message = "Couldn't load this.",
}: {
  onRetry?: () => void;
  message?: string;
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
      <p className="text-sm text-destructive">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

/** Shown when an admin-only query returns 403 for a non-admin. */
export function NoAccessState() {
  return (
    <EmptyState title="Admins only" message="This page is for admins." />
  );
}

/**
 * Optional helper that renders the right state for a TanStack query result:
 * loading → LoadingState, 403 → NoAccessState, other error → ErrorState (retry),
 * empty → `empty`, otherwise `children(data)`.
 */
export function QueryState<T>({
  query,
  children,
  loading,
  empty,
  isEmpty,
}: {
  query: UseQueryResult<T>;
  children: (data: T) => ReactNode;
  loading?: ReactNode;
  empty?: ReactNode;
  isEmpty?: (data: T) => boolean;
}) {
  if (query.isLoading) return <>{loading ?? <LoadingState />}</>;
  if (query.isError) {
    if (isForbidden(query.error)) return <NoAccessState />;
    return <ErrorState onRetry={() => query.refetch()} />;
  }
  if (query.data === undefined) return null;
  if (isEmpty?.(query.data)) {
    return (
      <>
        {empty ?? (
          <EmptyState title="Nothing here yet" message="There's nothing to show." />
        )}
      </>
    );
  }
  return <>{children(query.data)}</>;
}
