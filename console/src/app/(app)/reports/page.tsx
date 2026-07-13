import { redirect } from "next/navigation";

// On-demand report running folded into Schedules ("run now" on an existing
// schedule) plus the ⌘K palette's run actions. Keep this route working for
// old links/bookmarks by redirecting.
export default function ReportsPage() {
  redirect("/schedules");
}
