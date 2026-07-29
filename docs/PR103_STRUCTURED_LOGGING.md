# PR103 — Structured Logging

Atlas logging is silent by default. Enable it with global CLI options:

```text
atlas --log-level info --log-format json --correlation-id build-123 analyze .
atlas --log-level warning --log-format text --log-file .atlas/atlas.log check .
```

JSON records contain timestamp, level, logger, event, message, correlation ID,
thread, and structured fields. Workspace event-bus activity supplies analysis,
project, persistence, configuration, watch, and recovery lifecycle events.
Each event bus captures its invocation correlation ID, so events emitted by
PR73 worker threads retain the same trace identity.

Keys named `authorization`, `password`, `secret`, `token`, `api_key`, or
`apikey` are recursively replaced by `[REDACTED]`. Atlas configures only the
`moughorai` logger hierarchy and does not modify a host application's root
logger.

Library users can call `configure_logging()`, `get_logger()`, and
`log_event()`. Set the level to `off` to restore silent behavior.
