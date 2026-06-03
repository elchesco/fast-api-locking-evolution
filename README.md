# Code companion — locking evolution post

Each folder maps to one stage of the post's narrative:

```
00-the-bug/           the original race scenario, reproducible in 30 lines
01-advisory-lock/     pg_try_advisory_xact_lock per tick (attempt 1)
02-thread-sentinel/   select-by-title dedupe (attempt 2, the silent-fail trap)
03-claim-row/         worker_runs table + claim_run() helper (attempt 3)
04-cli-entrypoint/    jobs/ package + __main__.py + worker delegates
05-eventbridge/       phase-2 CDK sketch (not deployed yet)
```

## Suggested reading order

1. **`00-the-bug/`** — the minimal reproducer. Run two replicas of
   the script against a shared Postgres and watch the duplicate
   notifications land.
2. Each stage folder in order. Each one is a self-contained
   improvement; you can stop at any stage and still have something
   functional. The post argues that stopping earlier than `03-claim-row/`
   leaves you exposed.
3. **`05-eventbridge/`** — the structural ending. Not strictly needed
   if you're happy with the worker model, but it removes the entire
   "which replica fires the cron?" question.

## Notes

* `00-the-bug/` is a self-contained script — no models, no
  migrations. It uses a single ``notifications`` table created at the
  top of the file so you can drop into a fresh DB and reproduce in
  seconds.
* `03-claim-row/` contains both the migration and the Python helper.
  The `INSERT ... ON CONFLICT DO NOTHING RETURNING 1` pattern is the
  whole post in three lines of SQL — copy that file even if you skip
  everything else.
* `05-eventbridge/` is a CDK sketch — not a fully working stack,
  intentionally. Treat it as a wiring diagram. The IAM role + ECS
  task def references will need to match whatever your stack already
  has.
 
