"use client";

import { EmptyState, ErrorState, LoadingState, NoAccessState } from "@/components/common/states";
import { ReviewTrendsChart } from "@/components/system/review-trends-chart";
import { StatusPill } from "@/components/ui/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { isForbidden } from "@/lib/api";
import { Time } from "@/lib/time";
import { useReviewTrends } from "@/lib/use-system";
import { useReviews, type Review } from "@/lib/use-reviews";
import { useMe } from "@/lib/use-me";

export default function ReviewsPage() {
  const { data: me, isLoading: meLoading } = useMe();
  const reviews = useReviews();
  const { data: byWeek, isLoading: trendsLoading } = useReviewTrends(56);

  if (meLoading) return <LoadingState rows={5} />;
  if (!me?.is_admin) return <NoAccessState />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Reviews</h1>
        <p className="text-sm text-muted-foreground">Every PR Bott has reviewed, and how verdicts are trending</p>
      </div>

      <div className="rounded-xl border bg-card shadow-sm">
        <div className="border-b px-4 py-2.5 text-sm font-semibold">Review verdicts by week</div>
        <div className="p-4">
          {trendsLoading || !byWeek ? <Skeleton className="h-44" /> : <ReviewTrendsChart byWeek={byWeek} />}
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
        {reviews.isLoading ? (
          <LoadingState rows={6} />
        ) : reviews.isError ? (
          isForbidden(reviews.error) ? (
            <NoAccessState />
          ) : (
            <ErrorState message="Couldn't load reviews." onRetry={() => reviews.refetch()} />
          )
        ) : !reviews.data?.length ? (
          <EmptyState title="No reviews yet" message="Bott hasn't reviewed a PR." />
        ) : (
          <ul>
            {reviews.data.map((r: Review, i) => (
              <li
                key={`${r.pr}-${i}`}
                className="flex items-center gap-3 border-b px-4 py-3 last:border-b-0"
              >
                <div className="min-w-0 flex-1 truncate text-sm font-medium">
                  {r.url ? (
                    <a
                      href={r.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hover:text-primary hover:underline"
                    >
                      {r.pr}
                    </a>
                  ) : (
                    r.pr
                  )}
                </div>
                <StatusPill status={r.verdict} />
                <div className="w-24 flex-none text-right text-xs text-muted-foreground">
                  <Time value={r.created} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
