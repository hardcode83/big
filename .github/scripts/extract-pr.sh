#!/usr/bin/env bash
set -euo pipefail

extract_pr() {
  local message=${1-}
  local number
  local suffix_count
  suffix_count="$(printf '%s' "$message" | grep -oE '\(#[1-9][0-9]*\)' | wc -l | tr -d ' ' || true)"
  if [[ $message =~ ^Merge\ pull\ request\ #([1-9][0-9]*)[[:space:]] ]]; then
    [[ "$suffix_count" == 0 ]] || { printf '\n'; return 0; }
    number=${BASH_REMATCH[1]}
  elif [[ $(printf '%s' "$message" | grep -oE '\(#[1-9][0-9]*\)' | wc -l | tr -d ' ') == 1 ]] \
    && [[ $message =~ \(#([1-9][0-9]*)\)[[:space:]]*$ ]]; then
    number=${BASH_REMATCH[1]}
  else
    # Empty output is the contract's absence value. The backend treats any
    # incomplete combination atomically as provenance=null.
    printf '\n'
    return 0
  fi
  printf '%s\n' "$number"
}

self_test() {
  [[ $(extract_pr 'Merge pull request #42 from example/feature') == 42 ]]
  [[ $(extract_pr 'Ship provenance metadata (#43)') == 43 ]]
  [[ -z $(extract_pr 'Fix issue #44') ]]
  [[ -z $(extract_pr 'Ambiguous (#45) trailing text') ]]
  [[ -z $(extract_pr 'Title (#46) extra (#47)') ]]
  [[ -z $(extract_pr 'Merge pull request #42 from example/feature (#43)') ]]
  [[ -z $(extract_pr 'Merge pull request #0 from example/feature') ]]
  printf 'extract-pr self-test: ok\n'
}

if [[ ${1-} == --self-test ]]; then
  self_test
else
  extract_pr "${1-$(cat)}"
fi
