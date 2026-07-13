import { redirect } from "next/navigation";

// The Policy override editor was retired from the console. Action-policy rules
// (allow / gate / deny) still apply from their code defaults; the in-console
// override surface was removed to keep the admin area focused. Keep this route
// working for old links/bookmarks by redirecting to the admin landing page.
export default function PolicyPage() {
  redirect("/admin/system");
}
