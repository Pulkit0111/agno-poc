"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { JobDrawer, StatusBadge } from "@/components/jobs/job-drawer";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { relativeTime } from "@/lib/time";
import { useJobs } from "@/lib/use-jobs";
import { useMe } from "@/lib/use-me";

const FILTERS = ["all", "running", "done", "error"] as const;

function ActivityInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { data: me } = useMe();
  const scope = (params.get("scope") === "all" && me?.is_admin ? "all" : "mine") as "mine" | "all";
  const status = params.get("status") ?? "all";
  const selected = params.get("id") ? Number(params.get("id")) : null;
  const { data: jobs, isLoading } = useJobs(scope, 50);
  const visible = jobs?.filter((j) => status === "all" || j.status === status);

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    router.replace(`/activity?${next.toString()}`);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Activity</h1>
          <p className="text-sm text-muted-foreground">Every run — builds, reviews, reports, scheduled jobs</p>
        </div>
        {me?.is_admin && (
          <Tabs value={scope} onValueChange={(v) => setParam("scope", v === "mine" ? null : v)} className="ml-auto">
            <TabsList>
              <TabsTrigger value="mine">Mine</TabsTrigger>
              <TabsTrigger value="all">All users</TabsTrigger>
            </TabsList>
          </Tabs>
        )}
      </div>

      <div className="flex gap-2">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setParam("status", f === "all" ? null : f)}
            className={`rounded-full border px-3 py-1 text-xs font-medium capitalize ${
              status === f ? "border-primary/40 bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-xl border bg-card shadow-sm">
        {isLoading ? (
          <div className="space-y-2 p-4"><Skeleton className="h-9" /><Skeleton className="h-9" /><Skeleton className="h-9" /></div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible?.map((j) => (
                <TableRow key={j.id} className="cursor-pointer" onClick={() => setParam("id", String(j.id))}>
                  <TableCell className="font-medium">{j.kind}</TableCell>
                  <TableCell><StatusBadge status={j.status} /></TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground">{relativeTime(j.created)}</TableCell>
                </TableRow>
              ))}
              {!visible?.length && (
                <TableRow>
                  <TableCell colSpan={3} className="py-8 text-center text-sm text-muted-foreground">
                    No runs {status !== "all" ? `with status “${status}”` : "yet"}.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        )}
      </div>

      <JobDrawer id={selected} onClose={() => setParam("id", null)} />
    </div>
  );
}

export default function ActivityPage() {
  return (
    <Suspense>
      <ActivityInner />
    </Suspense>
  );
}
