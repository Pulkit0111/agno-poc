import { redirect } from "next/navigation";

// Health merged into the single admin System page (health + advisories + review
// trends). Keep this route working for old links/bookmarks by redirecting.
export default function HealthPage() {
  redirect("/admin/system");
}
