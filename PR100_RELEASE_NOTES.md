# Atlas 2.0 Release Notes — PR100

PR100 stabilizes Atlas 2.0. The package, Python API, CLI, and SARIF tool
identity now consistently report version 2.0.0. Release documentation covers
the capabilities delivered through PR99 and explicitly preserves existing
entry points, deterministic defaults, persisted schemas, and plugin/rule API
1.x compatibility.

The release gate builds and inspects the wheel, exercises the complete CLI and
enterprise feature flow, runs all tests, and replays the patch from PR99.
