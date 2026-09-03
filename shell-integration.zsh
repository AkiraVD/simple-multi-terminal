# simple-multi-terminal shell integration (zsh).
# Sourced from ~/.zshrc. Does nothing unless running inside the terminal.
#
# Same two jobs as the bash version:
#   1. Report the current directory via OSC 7 so tabs persist their path.
#   2. Notify when a long-running command finishes.
#
# Uses zsh's own preexec/precmd hooks rather than a DEBUG trap, so a normal
# prompt costs no subprocess.

[[ -n "$SMT_TAB_ID" ]] || return 0
[[ -o interactive ]] || return 0

# A clock finer than the threshold it feeds: $SECONDS is truncated at both
# ends, so a command that really ran 10.0s can measure 9 and never report.
# EPOCHREALTIME is a float parameter here, not the fixed-width string bash
# gives, so convert by arithmetic; an integer variable truncates on assignment.
zmodload -F zsh/datetime p:EPOCHREALTIME 2>/dev/null
typeset -gi __SMT_NOW __SMT_T0
if [[ -n "$EPOCHREALTIME" ]]; then
  __smt_now() { (( __SMT_NOW = EPOCHREALTIME * 1000000 )) }
else
  __smt_now() { (( __SMT_NOW = SECONDS * 1000000 )) }
fi

# Percent-encodes a path byte by byte. Only called for paths that actually
# need it, so the common prompt stays fork-free.
__smt_urlencode() (
  LC_ALL=C
  local str="$1" safe
  while [[ -n "$str" ]]; do
    safe="${str%%[^-_.~a-zA-Z0-9/]*}"
    printf '%s' "$safe"
    str="${str#"$safe"}"
    if [[ -n "$str" ]]; then
      printf '%%%02X' "'$str"
      str="${str#?}"
    fi
  done
)

# OSC 7 - tells VTE our working directory. This is what drives tab titles
# and the saved session.
__smt_osc7() {
  local path="$PWD"
  [[ "$path" =~ '^[-_.~a-zA-Z0-9/]*$' ]] || path="$(__smt_urlencode "$PWD")"
  printf '\033]7;file://%s%s\033\\' "${HOST:-${HOSTNAME:-localhost}}" "$path"
}

# OSC 6 - "a command is running", cleared at the next prompt. A printf rather
# than a call to smt-notify because it fires on every command, and a helper
# process per command is the cost this integration exists to avoid. The program
# name rides along when it needs no encoding; otherwise the tab just says
# something is running.
__smt_busy() {
  local prog=${1%% *}
  [[ "$prog" =~ '^[-_.+A-Za-z0-9]+$' ]] || prog=""
  printf '\033]6;file:///smt/busy/%s\033\\' "$prog"
}

__smt_idle() { printf '\033]6;\033\\' }

__smt_preexec() {
  __smt_now; __SMT_T0=$__SMT_NOW
  __SMT_CMD=$1
  # zsh's preexec only fires for commands you actually ran, so the guard the
  # bash side needs against its own rc is unnecessary here.
  __smt_busy "$1"
}

__smt_precmd() {
  local code=$?
  __smt_osc7
  __smt_idle
  if (( __SMT_T0 )); then
    __smt_now
    local elapsed=$(( (__SMT_NOW - __SMT_T0) / 1000000 ))
    __SMT_T0=0
    if (( elapsed >= ${SMT_NOTIFY_MIN_SECONDS:-10} )); then
      smt-notify command-done --exit "$code" --seconds "$elapsed" \
                 --command "$__SMT_CMD" 2>/dev/null
    fi
  fi
  return $code
}

autoload -Uz add-zsh-hook
add-zsh-hook preexec __smt_preexec
add-zsh-hook precmd __smt_precmd
__smt_osc7
