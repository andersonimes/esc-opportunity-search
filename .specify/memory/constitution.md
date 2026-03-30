# ESC Opportunity Search Constitution

## Core Principles

### I. Simplicity Over Abstraction

Write obvious, flat code. Prefer three similar lines over one premature abstraction. No helpers, utilities, or wrapper layers unless the same pattern appears in 4+ places and the abstraction clearly simplifies. Functions should be short enough to read without scrolling. If a new developer (or AI agent) can't understand a function in 30 seconds, it's too complex.

**Constraints:**
- No class hierarchies deeper than 1 level of inheritance
- No metaprogramming or dynamic dispatch unless absolutely necessary
- Prefer composition over inheritance
- Standard library over third-party packages whenever reasonable

### II. Perimeter Testing (NON-NEGOTIABLE)

Tests validate user journeys and external behavior at system boundaries — not internal implementation details. Every feature must have integration/functional tests that exercise the real entry points a user (or Claude via MCP) would hit. Internal unit tests are optional and only warranted when they genuinely aid development of complex logic.

**Constraints:**
- Every MCP tool must have tests that invoke it the way Claude would
- Every data pipeline step must have tests using realistic sample data
- No mocking of core dependencies (databases, APIs, vector stores) in perimeter tests — use real services, test containers, or recorded fixtures
- Test names describe the user-visible behavior being verified, not the implementation

### III. Agent-Readable Code

This codebase will be maintained by both humans and AI agents across sessions. Code must be understandable by an agent reading it cold with zero prior context.

**Constraints:**
- Clear, descriptive naming — no abbreviations except universally known ones (url, id, api)
- Explicit type hints on all function signatures
- README and CLAUDE.md must always reflect current reality — how to install, run, test, and deploy
- If an agent can't figure out how to work on this project from the repo alone, that's a bug

### IV. Minimal Dependencies

Every dependency is a maintenance burden and a security surface. Justify each one.

**Constraints:**
- Prefer Python standard library over third-party packages
- Pin all dependency versions explicitly
- Document why each dependency exists in pyproject.toml comments or README
- Audit dependencies before adding — check maintenance status, license, size

## Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.12+ | Broad ecosystem, Databricks native, MCP SDK available |
| Package manager | uv | Fast, modern, handles virtualenvs and lockfiles |
| MCP framework | mcp (official Python SDK) | Standard, maintained by Anthropic |
| Vector search | Databricks Vector Search (Free Edition) | Anderson works at Databricks, $0 cost |
| Storage | Databricks Delta tables | Integrated with Vector Search |
| Deployment | Proxmox LXC container | Existing home infrastructure |

## Quality Gates

| Gate | Checks |
|------|--------|
| Pre-commit | Type checking passes, linter passes, all tests pass |
| Pre-merge | Full test suite green, CLAUDE.md and README current |

## Development Workflow

- Feature branches: `NNN-feature-name` (managed by spec-kit)
- Commits: concise message explaining *why*, not *what*
- PRs: merge to main when tests pass and spec acceptance criteria met

## Governance

This constitution applies to all code in this repository. Amendments require updating this file with rationale for the change.

**Version**: 1.0.0 | **Ratified**: 2026-03-30
