# Kiroween 2026 — Neovarch Agent + Kiro Crew

## Introduction

Kiroween 2026 entry (Devpost, submission period 30 Oct–4 Dec 2026). The entry adds a Kiro-powered coding mode to Neovarch Agent: the agent on the user’s PC can hand a coding task to Kiro (IDE / CLI / Crew) and bring the result back into the chat, with the same approval flow as any other tool.

Status: SPEC ONLY. The feature is not built yet; this spec is the plan for work done with Kiro during the Kiroween period.

## Requirements

### Requirement 1 — Kiro as a Neovarch tool

**User Story:** As a Neovarch Agent user, I want to ask the agent to write or change code with Kiro, so I get Kiro-quality code edits without leaving the agent chat.

#### Acceptance Criteria

1. WHEN the user asks for a code change, THE Neovarch Agent SHALL offer a `kiro` tool that runs the task through Kiro.
2. WHEN the `kiro` tool runs, THE Neovarch Agent SHALL pass the task, the target files, and the repo context to Kiro.
3. WHEN Kiro proposes file changes, THE Neovarch Agent SHALL show the diff and wait for the user’s approval before applying it, following the existing `ask` approval mode.
4. WHEN the user rejects the diff, THE Neovarch Agent SHALL discard it and report that nothing was changed.

### Requirement 2 — Kiro spec awareness

**User Story:** As a developer, I want Neovarch Agent to understand Kiro specs and steering files, so Kiro-driven work follows the repo’s own rules.

#### Acceptance Criteria

1. WHEN a repo contains a `.kiro` directory, THE Neovarch Agent SHALL read its steering files before starting a `kiro` task.
2. WHEN a repo contains `.kiro/specs/`, THE Neovarch Agent SHALL list the available specs to the user on request.

### Requirement 3 — Safe by default

**User Story:** As a user, I want Kiro-driven changes to be as safe as any other agent action, so my PC is never modified without my say-so.

#### Acceptance Criteria

1. WHEN the `kiro` tool runs, THE Neovarch Agent SHALL NOT apply file changes without approval in `ask` mode.
2. WHEN the `kiro` tool runs, THE Neovarch Agent SHALL NOT read or send API keys; secrets stay in `~/.neovarch/.env`.
