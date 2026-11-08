# Independent review of the existing GREEN patch

Scope: the complete working-tree production diff against HEAD
`4487c1d93c77c117b1c18c0f611cd76152e3a011`, on
`feat/vt013-undo-manhpd`. The original assignment baseline remains
`a2e0c070d694054001767979fe3f247e7ebff6be`.
All changed production lines are preserved in the zero-context
`reviewed-production.diff`; the normal full-context diff was also inspected.
No production file is changed in this VERIFY phase.

## Persistence contract and invariant

- `query-api/src/assistant/storage.py:66`, `_state`: validate the stored schema,
  cluster identity and actual integer version metadata, then deep-copy the source.
  OpenSearch metadata stays outside `_source`.
- `storage.py:113`, `ConversationRepository.get`: only a genuine missing document
  represents absence. Missing indexes and other storage errors raise `StorageError`.
- `storage.py:130`, `_write`: an absent conversation uses `client.create` with
  `refresh="wait_for"`. An existing conversation uses `client.index` with both
  `if_seq_no=previous.seq_no` and `if_primary_term=previous.primary_term` and
  `refresh="wait_for"`. There is no unconditional conflict fallback.
- `storage.py:155`, `save`: new completed history and a deep-copied previous message
  array are written together in one document. The snapshot contains no nested Undo.
- `storage.py:168`, `undo`: compare revision before inspecting the snapshot;
  restore exactly its messages, retain creation time, change modification time,
  consume the snapshot with `undo=null`, and use the same conditional-write path.
- `query-api/src/assistant/router.py:26` and `:38`: strict request strings, extra
  fields forbidden, raw message length 1–4000 with blank rejection, canonical
  signed-64-bit-bounded revision syntax. Rejections are HTTP 422.
- `router.py:49`: public GET/Send/Undo projection has exactly `cluster_id`,
  `messages`, `revision`, `undo_available`. Persisted empty history has a real
  revision; absence has null revision. The snapshot is private.
- `router.py:94` and `:135`: conflicts become HTTP 409; storage failures escape to
  `query-api/src/main.py:130` and its existing HTTP 503 storage-error envelope.
  Generation failures retain the HTTP 502 path. Undo does not invoke generation.
- `main.py:119`: the whole Assistant router still depends on `require_admin`.
  Integration tests seed an actual Argon2 admin in their own users index, log in
  through `/auth/login`, and use the returned JWT. No auth dependency is overridden.

The invariant is **at most one mutation based on the same persisted version can
commit, and its history and recovery data must be committed atomically**.
The successful OpenSearch write supplies the response revision. The competing
create/CAS write must yield HTTP 409 and must not alter the winner's source.
No timestamp is used as a concurrency token.

## Differences that fake-based tests cannot establish

1. Real missing-document 404s have `info.found=false`, while their `.error` string
   is the serialized response body. Missing-index errors have a different nested
   error envelope and `.error="index_not_found_exception"`. Actual shapes are
   recorded in each run's `not-found-shapes.json`.
2. OpenSearch checks and returns sequence numbers/primary terms, performs create-only
   and CAS arbitration, and provides real typed SDK conflicts. A transport fake
   cannot prove HTTP parameter serialization or server enforcement. Sequence numbers
   belong to a shard, not a document-wide counter; the tests assert exact increments
   only in fresh single-shard conversation indexes containing one document.
3. The server validates strict mappings and normalizes `messages.dynamic` to the
   string `"false"`. Real additive mapping upgrade and a rejected unexpected field
   are checked; before/after mappings are captured in `mapping-upgrade.json`.
4. JSON serialization, tool-message null values, Unicode, `_source` preservation,
   real refresh behavior and independent API processes are exercised. The fake
   does not model those infrastructure boundaries.
5. Real connection refusal and OpenSearch's write-block rejection exercise SDK
   error propagation. These are not a fake returning default data or a synthetic
   `StorageError`. Final raw source and version must equal their pre-failure values.

## Client/server compatibility

The reused host environment contains `opensearch-py 3.2.0`. The release's
[official compatibility matrix](https://raw.githubusercontent.com/opensearch-project/opensearch-py/v3.2.0/COMPATIBILITY.md)
supports client 3.x against server 2.x provided removed features are not used.
The patch uses document Get/Create/Index, conditional-write parameters and index
mapping APIs. This is a documented compatibility claim; empirical verification is
reported separately in `results.json`, JUnit and the README.

`query-api/requirements.txt:6` permits `opensearch-py>=2.6` without an upper bound.
The exact host and freshly built image versions are recorded, rather than assuming
every permitted future or minimum client version was tested. The official
[OpenSearch 2.17 Docker instructions](https://docs.opensearch.org/2.17/install-and-configure/install-opensearch/docker/)
describe pinning `2.17.1`; this runner always pins it and checks the server's own
version/unique cluster identity before any test writes.

## Dockerfile and schema packaging

`query-api/Dockerfile:18` adds a single schema COPY. The file at runtime must be
`/app/docs/architect/contracts/assistant-conversation-schema.json`, matching
`storage.py:21`'s `parents[3]` resolution. The root `.dockerignore` excludes tests
but does not exclude that JSON schema. No dependency declaration changed.
Building uses the actual Query API Dockerfile, not a substitute. A network-disabled
runtime probe imports the actual storage module under the non-root image user and
asserts schema existence and Python 3.11. A separate disposable test image adds only
the already declared development dependency `pytest>=8`; test files are mounted
read-only because deployment images exclude them. This does not modify the
production image or install anything into the host environment.

## Limits and risks retained for review

- `ingestion/src/storage.py:127` still configures shared SDK retries
  (`max_retries=2`, `retry_on_timeout=True`). The repository adds no application
  retry/rebase loop, and retries retain CAS/create-only arguments. However, a
  response lost after commit remains an uncertain outcome; a transport retry can
  surface a conflict after that successful commit. These tests do not inject a
  lost response or establish outcome certainty on timeout. Clients must reconcile
  through GET as specified in the approved plan.
- The real-instance tests cover Send/Send (initial and existing) and Undo/Undo.
  Send/Undo interleaving remains covered by the existing fake-based backend suite,
  not by a new real-server test in this requested slice.
- The isolated server uses one node, one shard, zero replicas and disposable tmpfs
  data. API-process restart is tested; OpenSearch-node restart, failover, replica
  promotion and primary-term changes are not tested.
- OpenSearch security is disabled only on this owned disposable node, reachable
  on a random loopback host port. Application admin authentication remains real.
  OpenSearch TLS/security-plugin integration is not tested.
- Generation is deterministic and test-only; no Azure/tool execution is claimed.
  Restoring tool messages is checked by exact equality of already persisted data.
- No frontend, mutation or 60-task performance test is run in this phase. A
  successful verification is readiness for the next implementation stage, not a
  deployment, performance or complete-assignment approval.
- Graphify's existing index predates the GREEN patch. It was used only for
  navigation; source and actual executions, not graph relationships, support the
  conclusions above. Its unrelated output was not changed.
