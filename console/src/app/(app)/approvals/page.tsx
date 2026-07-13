import { redirect } from "next/navigation";

// Approvals now lives inline on Home ("Needs a decision" / "Waiting on an
// admin"). Keep this route working for old links/bookmarks by redirecting.
export default function ApprovalsPage() {
  redirect("/");
}
