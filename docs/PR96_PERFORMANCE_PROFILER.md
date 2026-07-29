# PR96 — Performance Profiler

Run an analysis with opt-in timing:

```text
atlas profile . --workers 4
atlas profile . --project api
```

The JSON report contains stable metric names and aggregate call, total,
minimum, maximum, and average milliseconds. Project analyzers are wrapped
without changing their result or exception behavior. Collection is
thread-safe for PR73 concurrent workers. Timings are never added to ordinary
deterministic analysis reports.
