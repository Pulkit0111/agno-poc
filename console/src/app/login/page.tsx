"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

const ERRORS: Record<string, string> = {
  wrong_domain: "That account isn't on the company domain. Use your Axelerant Slack account.",
  bad_state: "Your sign-in link expired. Please try again.",
  oidc_failed: "Sign-in didn't complete. Please try again.",
};

function LoginError() {
  const error = useSearchParams().get("error");
  if (!error) return null;
  const message = ERRORS[error] ?? "Sign-in didn't complete. Please try again.";
  return (
    <div
      role="alert"
      className="mt-6 flex items-start gap-2.5 rounded-lg border border-destructive/30 bg-destructive/10 px-3.5 py-3 text-left text-sm text-destructive"
    >
      <AlertTriangle className="mt-0.5 size-4 flex-none" />
      <div>
        <div className="font-medium">Couldn&apos;t sign you in</div>
        <p className="mt-0.5 text-destructive/90">{message}</p>
        <a href="/api/console/auth/login" className="mt-1 inline-block font-medium underline underline-offset-2">
          Try again
        </a>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <main className="grid min-h-screen place-items-center bg-background">
      <div className="w-[360px] rounded-xl border bg-card p-9 text-center shadow-sm">
        <div className="mx-auto mb-4 grid size-11 place-items-center rounded-xl bg-primary text-lg font-bold text-primary-foreground">
          B
        </div>
        <h1 className="font-display text-lg tracking-tight">Bott Console</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Manage your approvals, schedules, skills and more. Conversations stay in Slack.
        </p>
        <Suspense fallback={null}>
          <LoginError />
        </Suspense>
        <Button
          render={<a href="/api/console/auth/login" />}
          nativeButton={false}
          className="mt-6 w-full"
        >
          Continue with Slack
        </Button>
        <p className="mt-4 text-xs text-muted-foreground">
          Uses your Axelerant Slack identity — the same one Bott already knows.
        </p>
      </div>
    </main>
  );
}
