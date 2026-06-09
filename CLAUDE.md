# Claude Instructions — immich-flickr-sync

See [AGENTS.md](AGENTS.md) for project architecture, invariants, and test approach. This file adds Claude Code-specific guidance.

## Development workflow

Use Claude Superpowers. Update the spec and create a plan for every feature 

Use TDD: write failing tests first, then implement. Run `pytest` (not `python -m pytest`) — the venv is active in this project.

Do not `source .venv/bin/activate` in subagent tasks — the venv is already on PATH.

## Commit style

Follow the existing commit history: `type: short description` (no scope), imperative mood, lowercase. Types used: `feat`, `fix`, `chore`, `docs`.

## What not to do

- Do not add comments explaining what code does — name things clearly instead.
- Do not add error handling for impossible cases or internal invariants.
- Do not add backwards-compatibility shims when you can just change the code.
