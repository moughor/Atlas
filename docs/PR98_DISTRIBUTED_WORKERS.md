# PR98 — Distributed Workers

`DistributedWorkspaceCoordinator` maps workspace projects to PR58 distributed
jobs. Project dependencies become lease dependencies; `language` options
become worker capabilities; project configuration produces stable SHA-256 job
fingerprints; and successful dependency results are supplied to downstream
workers.

The coordinator supports registration, heartbeats, lease expiry, retries, and
transport adapters through the existing PR58 API. PR98 adds an in-process
workspace driver for deterministic testing and single-host use, but does not
claim or require a particular HTTP, RPC, or queue deployment.
