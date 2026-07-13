import { redirect } from "next/navigation";

// Reviews merged into the single admin System page (health + advisories + review
// trends). Keep this route working for old links/bookmarks by redirecting.
export default function ReviewsPage() {
  redirect("/admin/system");
}
