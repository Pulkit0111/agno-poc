import { redirect } from "next/navigation";

// The old System page has been split: model/connectors/jobs now live on
// /admin/health and the review-verdict trends moved to /admin/reviews.
// Keep this route working by redirecting to Health.
export default function SystemPage() {
  redirect("/admin/health");
}
