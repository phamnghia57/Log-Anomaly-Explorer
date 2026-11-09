# Frontend test results

38 unique new API/component cases: 37 original RED failures plus one later session-race failure. All 38 pass in final GREEN; they also pass with the 102 existing cases in the 140-case regression run.

- `VT-013 Assistant Undo UI and React Query cache > F-01 Undo availability flag=true revision="1:0"` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-01 Undo availability flag=true revision="9223372036854775807:9223372036854775807"` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-01 Undo availability flag=false revision="1:7"` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-01 Undo availability flag=true revision=null` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-01 Undo availability flag=true revision=""` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-01 Undo availability flag=true revision="01:0"` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-01 Undo availability flag=true revision="1:0\n"` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-01 Undo availability flag=true revision="1:9223372036854775808"` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-01 Undo availability flag=true revision=7` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-01 Undo availability flag="true" revision="1:7"` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-01 Undo availability flag=undefined revision=undefined` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-02/03 keyboard Undo uses current authenticated revision and exact server history, without optimistic deletion` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-03 first-Send Undo accepts the server's persisted empty history` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-04 HTTP 409 GET-reconciles newer messages, never guesses or retries Undo` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-05 503 preserves history until GET confirms the uncertain outcome` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-05 network preserves history until GET confirms the uncertain outcome` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-05 failed reconciliation retains messages and disables stale Undo until a manual GET succeeds` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-06 pending Undo blocks double-clicks, Send and Enter without discarding the draft` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-06 pending Send blocks Undo and duplicate Sends` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-07 a new QueryClient remount loads the restored history using GET` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-08 Stop aborts only Send, restores draft, GET-reconciles and never calls Undo` — **PASS**. RED FAIL: aborted Send remained pending/input disabled under the global mutation retry policy; later GET assertions were not reached.
- `VT-013 Assistant Undo UI and React Query cache > F-09 a late GET started before Undo cannot overwrite its confirmed response` — **PASS**. RED FAIL: Undo action absent.
- `VT-013 Assistant Undo UI and React Query cache > F-10 logout during a confirmed Undo cache update cannot repopulate cleared private state` — **PASS**. Follow-up RED FAIL: confirmed Undo repopulated cache cleared during logout.
- `VT-013 Undo API contract > F-02 sends the current opaque revision and existing Bearer header to encoded cluster path` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-01 accepts valid revision boundary 1:0 unchanged` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-01 accepts valid revision boundary 9223372036854775807:9223372036854775807 unchanged` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-01 rejects invalid revision "" before a request` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-01 rejects invalid revision "0:0" before a request` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-01 rejects invalid revision "01:0" before a request` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-01 rejects invalid revision "1:00" before a request` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-01 rejects invalid revision "1:-1" before a request` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-01 rejects invalid revision "1:0\n" before a request` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-01 rejects invalid revision "１:0" before a request` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-01 rejects invalid revision "1:9223372036854775808" before a request` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-04/05 preserves HTTP 409 as an error, never a default conversation` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-04/05 preserves HTTP 503 as an error, never a default conversation` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-05 propagates a network failure` — **PASS**. RED FAIL: new public Undo client function absent.
- `VT-013 Undo API contract > F-02 does not fetch without a valid admin session` — **PASS**. RED FAIL: new public Undo client function absent.

Real browser: **PASS**, one Chrome scenario using actual Query API, admin login, deterministic generation and disposable OpenSearch 2.17.1. Reload GET and raw persisted source/version equality are asserted; no route interception is used.

Application typecheck, standalone Playwright typecheck, lint and production build exit 0. Historical diagnostics and the standalone TypeScript command correction remain documented in README.md.
