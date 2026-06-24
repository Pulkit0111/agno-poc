#!/bin/sh
# Mirror `main` -> the stakeholder review branch on every push to `origin`.
#
# Invoked by .git/hooks/pre-push (which guards on remote == origin, so this only runs for
# origin pushes and never recurses into itself). Reads the pre-push ref lines on stdin and,
# for the push of `main`, fast-forwards the review branch.
#
# Safety: fast-forward only (no --force). If the review branch has diverged or the network
# is down, it warns and exits 0 so the user's push to origin is never blocked.

TARGET_REMOTE="axelerant"
TARGET_BRANCH="bott-agno-poc"

# stdin lines: <local ref> <local sha> <remote ref> <remote sha>
while read -r local_ref local_sha remote_ref remote_sha; do
  [ "$remote_ref" = "refs/heads/main" ] || continue
  # Skip branch deletions (all-zero sha).
  case "$local_sha" in *[!0]*) ;; *) continue ;; esac

  echo "↪ mirroring main → ${TARGET_REMOTE}/${TARGET_BRANCH} (fast-forward only)…"
  if git push "$TARGET_REMOTE" "${local_sha}:refs/heads/${TARGET_BRANCH}"; then
    echo "✓ review branch updated to ${local_sha}"
  else
    echo "⚠ mirror to ${TARGET_REMOTE}/${TARGET_BRANCH} failed (diverged or network)." >&2
    echo "  Your push to origin still went through; sync the review branch manually if needed." >&2
  fi
done

exit 0
