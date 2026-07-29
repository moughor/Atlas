# PR99 Release Notes

PR99 adds opt-in governance with viewer, analyst, and administrator roles;
action, project, worker, and force-analysis constraints; PR71 option parsing;
and append-only SHA-256-chained audit records.

`atlas governance <workspace>` verifies the durable audit chain. Existing CLI
users remain compatible because authorization is not silently enabled.
