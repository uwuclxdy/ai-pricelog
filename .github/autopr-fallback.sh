#!/bin/bash
# autopr-fallback: decide whether the cron fallback should dispatch a real
# autopr run. the box-side timer is the primary hourly trigger; these marks
# exist for when the box is down, and the check reads the autopr workflow's
# runs — never this workflow's own, so its own skipped fires can never read
# as a pipeline run and suppress a real one.
#
# stdin: `gh run list --workflow autopr --limit 1 --json databaseId,status,startedAt`
#        (newest autopr run; empty list when none exists yet)
# out:   "dispatch" or "skip" on stdout; exit 0 on a decided verdict, nonzero
#        on unparseable input, so a broken check reds its job instead of guessing
# the 3300s window leaves a [55,60)-minute band where a late-delivered mark can
# dispatch a duplicate run; autopr's concurrency group queues it behind the live
# run, and only serialized that way is it the no-op it is priced as (its pending
# scan then finds every model covered) — concurrent duplicates race the scan
# and both open PRs (observed 2026-09-22). the 300s headroom is what keeps a
# seconds-late systemd timer fire from suppressing the next one
set -euo pipefail
jq -er '
  if length == 0 then "dispatch"
  elif .[0].status != "completed" then "skip"
  elif .[0].startedAt == null then "dispatch"
  elif ((now - (.[0].startedAt | fromdateiso8601)) < 3300) then "skip"
  else "dispatch" end
'
