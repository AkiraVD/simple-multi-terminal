#!/usr/bin/env bash
# Manual test for the long-command notification.
#
#   ./test-notify.sh            # runs 15s, exits 0
#   ./test-notify.sh 20         # runs 20s
#   ./test-notify.sh 15 1       # runs 15s, exits 1 (check the failure wording)
#
# The notification only fires for a tab you are NOT looking at, so switch
# away before the countdown ends. It prints a reminder for the first 3s.

secs=${1:-15}
code=${2:-0}

# The timing hook lives in the parent interactive shell (a DEBUG trap under
# bash, preexec/precmd under zsh), so a subshell cannot see it.
# All we can check here is that the terminal exported its socket into the tab.
if [[ -z "$SMT_TAB_ID" || -z "$SMT_SOCKET" ]]; then
  echo "not inside SMT (SMT_TAB_ID/SMT_SOCKET unset) - nothing will notify" >&2
fi

echo "running for ${secs}s, will exit ${code}"
echo "threshold is ${SMT_NOTIFY_MIN_SECONDS:-10}s -> $( (( secs >= ${SMT_NOTIFY_MIN_SECONDS:-10} )) && echo "should notify" || echo "should NOT notify" )"
echo
echo ">>> switch to another tab or another window NOW <<<"

for (( i = secs; i > 0; i-- )); do
  printf '\r%3ds remaining ' "$i"
  sleep 1
done
printf '\rdone            \n'

exit "$code"
