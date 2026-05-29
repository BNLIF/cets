# ADR-0005: HWDB uploads run in a client-side thread pool

- **Status:** Accepted
- **Date:** 2026-05-29

## Context

The current LArASIC upload (`hwdb/upload/larasic.py`, driven by
`_stream_upload` in `hwdb/views.py`) is a serial `for chip in chips:` loop. Per
chip it issues 5–8 HTTP calls to HWDB at FNAL (find-or-create, location,
per-env dedup GET, test POST, optional CSV attach, optional `qaqc_uploaded`
PATCH). At ~150ms RTT and no TCP/TLS reuse, each chip takes ~1.5s; a full
~12k-chip backlog runs ~5 hours.

We looked for server-side batching against the official HWDB tutorial
(`dune.github.io/computing-HWDB/aio/`) and the official Python tool
(`DUNE/DUNE-HWDB-Python`, cached under `.idea/ref/`). Findings:

- **There is no bulk endpoint for tests.** `POST /components/{id}/tests` is
  single-record only. The 24k test POSTs that dominate our run cannot be
  collapsed server-side.
- Bulk endpoints exist **for items only**: `bulk-add`, `bulk-update`,
  `bulk-enable`. `bulk-add` takes a shared spec body plus a count and returns
  N part_ids — it does not accept per-item serial numbers or specs, so it
  cannot represent a LArASIC create (each chip needs a unique serial and
  `LOT N`).
- The official tool achieves throughput via **client-side parallelism**:
  `multiprocessing.dummy.Pool(25)` for writes, `ThreadPoolExecutor(50)` for
  reads, with a `requests.Session` per worker thread.

## Decision

Add a **parallel upload path** that runs `upload_chip` in a 10-worker thread
pool, alongside (not replacing) the existing serial path.

- **Per-tray scope.** The new path operates on one tray at a time, same as
  today. No outer "all pending" loop — keeps each run bounded (~20s) and
  failure recovery simple.
- **Two submit buttons on the existing upload form.** "Upload" (serial,
  existing) and "Parallel upload (×10)" (new). Both POST to
  `hwdb:upload_run`; the view dispatches on `request.POST.get("mode")`. PROD
  gauntlet, `force`, `attach_csvs`, `chip` filter, and the dev-only
  `random_5` apply to both unchanged.
- **10 workers default**, overridable via `?workers=N` (clamped 1–32) so we
  can tune empirically without redeploying.
- **`requests.Session()` lives on `FnalDbApiClient`.** Both paths benefit:
  the serial path picks up TCP+TLS keep-alive (~30% speedup); the parallel
  path instantiates one client (and therefore one Session) per worker thread.
- **Collapse the per-env dedup GET.** One `get_tests(part_id, history=True)`
  per chip replaces today's two `find_existing_test` calls (one per env);
  partition client-side.
- **Continue-on-error**, matching today. No circuit breaker — the operator
  watches the stream and aborts if they see a wall of failures.
- **Completion-order streaming.** The parallel path emits one line per chip
  prefixed with a monotonic `[done k/total]` counter, not the chip's input
  position. Same content otherwise (`sn-xxxx: created/exists, RT=..., LN=...`).

## Consequences

- A ~96-chip tray drops from ~3 min to ~15–20s. The full backlog still
  requires ~125 button clicks under the per-tray scope; an "all pending"
  outer loop is intentionally deferred until that's a real pain point.
- `FnalDbApiClient` becomes stateful (owns a Session). Callers should not
  share one client across threads — `requests.Session` is documented as
  not-fully-thread-safe. The parallel orchestrator constructs N clients up
  front; the serial path is unaffected.
- The parallel path's failure mode under a wide HWDB outage is "burn through
  10 chips in parallel before the operator hits stop." Considered and
  accepted; matches the serial path's existing trust-the-operator stance
  ([[0002-per-request-bearer-minting]] gives us a long-lived bearer per
  request, so the run is not authentication-bound).
- Bearer minting stays per-HTTP-request as today
  ([[0002-per-request-bearer-minting]]). One mint, ~10h lease, ample for a
  20-second tray run.
- We deliberately did **not** adopt the bulk item endpoints — they don't fit
  LArASIC's per-chip specs. Re-evaluate only if HWDB grows a true bulk-test
  endpoint or a bulk-add variant that accepts per-item bodies.
