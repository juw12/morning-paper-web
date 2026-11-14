#!/usr/bin/env bash
# Save the data folder as one commit on the data branch and print the commit id.
#
#   scripts/social_save.sh "<message>" [parent commit]
#
# With no parent the commit has no history, so the branch never grows: every run replaces it. With a
# parent (the commit this same run made a minute earlier) that first commit stays reachable, and the
# card images Buffer was told to fetch from it keep working until the next run.
set -euo pipefail

message="${1:?commit message}"
parent="${2:-}"
folder="${DATA_DIR:-data}"
branch="${DATA_BRANCH:-social-data}"
remote="${DATA_REMOTE:-origin}"

git -C "$folder" add -A
tree="$(git -C "$folder" write-tree)"
if [ -n "$parent" ]; then
  commit="$(git -C "$folder" commit-tree "$tree" -p "$parent" -m "$message")"
else
  commit="$(git -C "$folder" commit-tree "$tree" -m "$message")"
fi

for attempt in 1 2 3 4 5; do
  if git -C "$folder" push --quiet --force "$remote" "$commit:refs/heads/$branch" >&2; then
    echo "$commit"
    exit 0
  fi
  echo "push attempt $attempt failed" >&2
  sleep $((attempt * 5))
done
echo "could not save the data branch" >&2
exit 1
