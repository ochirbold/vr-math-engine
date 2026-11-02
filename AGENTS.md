# Repository rules

- This directory is an independent repository. Do not edit files in its parent project.
- Keep the mathematical core independent of databases, HTTP frameworks and environment state.
- Services own their stores; never read another service's SQLite file.
- Do not connect to production Oracle or perform source-data writes without an explicit indicator/scenario scope.
- Validate changes with `python -m pytest -q` from this repository after installing `.[test]`.
- Keep examples numeric and independently understandable. Do not hard-code CVP variable names in the core.
- Record limitations honestly; artifact persistence is not Oracle writeback.
- No credentials, local databases or virtual environments in Git.
