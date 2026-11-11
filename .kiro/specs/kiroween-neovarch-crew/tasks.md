# Implementation Plan — Neovarch Agent + Kiro Crew

Status: IN PROGRESS — items 1.x and 2.x done and tested (17 new tests in core/tests/test_kiro_tool.py); 3.x (demo video + submit) remains.

- [x] 1. Add the `kiro` tool to the Neovarch core
  - [x] 1.1 Define the tool schema (task, files, repo context) next to the existing tools (`shell`, `read_file`, `write_file`, `edit_file`).
  - [x] 1.2 Wire the tool to invoke Kiro CLI for the task and capture its proposed diff.
  - [x] 1.3 Route proposed diffs through the existing `ask` approval flow.
- [x] 2. Teach the agent to read `.kiro` steering and specs
  - [x] 2.1 Load `.kiro/steering/*.md` as context before a `kiro` task.
  - [x] 2.2 Add a command to list `.kiro/specs/` for the current repo.
- [ ] 3. Demo and submission
  - [ ] 3.1 Record a public YouTube demo under 3 minutes showing a code task done through the agent with Kiro.
  - [ ] 3.2 Write the Devpost submission (description, app URL, how Kiro was used) and submit before 5 Dec 2026 05:00 WIB.
