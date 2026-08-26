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

[[ -n "$SMT_TAB_ID" ]] || return 0
[[ $- == *i* ]] || return 0

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
  __SMT_T0=${EPOCHREALTIME/./}
  __SMT_CMD=$BASH_COMMAND
}

__smt_precmd() {
  local code=$?
  __smt_osc7
  if [[ -n "$__SMT_RUNNING" ]]; then
    local elapsed=$(( (${EPOCHREALTIME/./} - __SMT_T0) / 1000000 ))
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
