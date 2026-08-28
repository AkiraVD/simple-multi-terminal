# simple-multi-terminal shell integration (bash).
# Sourced from ~/.bashrc. Does nothing unless running inside the terminal.
#
# Two jobs:
#   1. Report the current directory via OSC 7 so tabs persist their path.
#   2. Notify when a long-running command finishes.
#
# Cost on a normal prompt is two shell builtins and one printf. The helper
# process only ever spawns after a command that already ran for 10+ seconds,
# so the overhead is irrelevant by construction.
#
# Timing wants a clock finer than the threshold it feeds. $SECONDS is
# truncated at both ends, so a command that really ran 10.0s can measure 9 and
# never report; $EPOCHREALTIME counts microseconds and does not. It arrived in
# bash 5 though, and macOS still ships 3.2 as /bin/bash, so pick once at
# startup rather than testing on every prompt.

[[ -n "$SMT_TAB_ID" ]] || return 0
[[ $- == *i* ]] || return 0

if [[ -n "$EPOCHREALTIME" ]]; then
  # The decimal separator follows LC_NUMERIC and is a comma in some locales,
  # so drop whatever is not a digit instead of assuming a dot. The fraction is
  # always six digits, which makes what is left a microsecond count.
  __smt_now() { __SMT_NOW=${EPOCHREALTIME//[!0-9]/}; }
else
  __smt_now() { __SMT_NOW=$(( SECONDS * 1000000 )); }
fi

__smt_urlencode() {
  local s="$1" out="" c
  for (( i=0; i<${#s}; i++ )); do
    c="${s:i:1}"
    case "$c" in
      [-_.~a-zA-Z0-9/]) out+="$c" ;;
      *) printf -v c '%%%02X' "'$c"; out+="$c" ;;
    esac
  done
  printf '%s' "$out"
}

# OSC 7 - tells VTE our working directory. This is what drives tab titles
# and the saved session.
__smt_osc7() {
  printf '\033]7;file://%s%s\033\\' "${HOSTNAME:-localhost}" "$(__smt_urlencode "$PWD")"
}

# DEBUG fires before each command. Record when it started and what it was.
__smt_preexec() {
  [[ -n "$COMP_LINE" ]] && return                 # tab-completion, not a command
  [[ -n "$__SMT_RUNNING" ]] && return             # only the first command of a line
  [[ "$BASH_COMMAND" == "__smt_precmd"* ]] && return
  __SMT_RUNNING=1
  __smt_now; __SMT_T0=$__SMT_NOW
  __SMT_CMD=$BASH_COMMAND
}

__smt_precmd() {
  local code=$?
  __smt_osc7
  if [[ -n "$__SMT_RUNNING" ]]; then
    __smt_now
    local elapsed=$(( (__SMT_NOW - __SMT_T0) / 1000000 ))
    unset __SMT_RUNNING
    if (( elapsed >= ${SMT_NOTIFY_MIN_SECONDS:-10} )); then
      smt-notify command-done --exit "$code" --seconds "$elapsed" \
                 --command "$__SMT_CMD" 2>/dev/null
    fi
  fi
  return $code
}

trap '__smt_preexec' DEBUG
# Prepend ours so we read $? before anything else clobbers it.
PROMPT_COMMAND="__smt_precmd${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
__smt_osc7
