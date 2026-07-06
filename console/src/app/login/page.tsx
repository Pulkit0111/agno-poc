import { Button } from "@/components/ui/button";

export default function LoginPage() {
  return (
    <main className="grid min-h-screen place-items-center bg-background">
      <div className="w-[360px] rounded-xl border bg-card p-9 text-center shadow-sm">
        <div className="mx-auto mb-4 grid size-11 place-items-center rounded-xl bg-primary text-lg font-bold text-primary-foreground">
          B
        </div>
        <h1 className="text-lg font-semibold tracking-tight">Bott Console</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Manage your approvals, schedules, skills and more. Conversations stay in Slack.
        </p>
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
