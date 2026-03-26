## DevMesh Rulebook (v3.0)

This rulebook is sent to every agent on connect and should be treated as **binding**.

### Core coordination rules

- **R01 — Framework Authority**: First model to connect becomes **ARCHITECT**. It creates the project skeleton and a dependency graph before execution begins.
- **R02 — Planner Phase**: ARCHITECT produces a task graph. Non-trivial work should wait until the framework is ready.
- **R03 — No Task Assignment**: Agents do not command each other; the server arbitrates.
- **R04 — Lock Hierarchy**: INTENT → WRITE → READ; CO_WRITE is collaborative.
- **R05 — Heartbeat Obligation**: If you hold a lock, heartbeat regularly or the server will auto-release and abandon the task.
- **R06 — Critic Requirement**: If `critic_required`, do not complete without a second agent’s approval.
- **R07 — Hardware Throttle**: Respect shared resource limits.
- **R08 — Read Before Work**: Non-architect agents read the framework context before acting.
- **R09 — Diff-Based Writes**: Prefer diffs/patches; avoid conflicting edits.
- **R10 — Pub/Sub File Events**: Use file event broadcasts rather than polling.

### Execution and UX rules

- **R11 — Environment Awareness**: Treat `working_dir` as the project root. Do not assume `/tmp`.
- **R12 — Autonomous Completion**: If the user provides a task without choices, choose sensible defaults and proceed end-to-end. Ask questions only if blocked.
- **R13 — UI Is Not an Editor**: Assume the web UI cannot apply diffs. Agents should still complete tasks and produce outputs; the user can request revisions afterward.

