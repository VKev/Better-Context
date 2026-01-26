---
name: worker-agent
description: Comprehensive worker agent instructions for executing tasks using beads and agent mail.
---

# Worker Agent Skill

## Overview
Instructions for an autonomous worker agent that systematically executes tasks using the `beads` (br) task tracking system and coordinates via `mcp_agent_mail`.

## Core Loop
1. **Initialize**: Register with Agent Mail, introduce yourself.
2. **Select Task**: Use `bv --robot-triage` to find the highest-impact ready work.
3. **Claim & Reserve**:
   - Reserve relevant files (`file_reservation_paths`)
   - Mark task in-progress (`br update <ID> --status in_progress`)
   - Announce start on Agent Mail (`send_message` with thread_id matching bead ID)
4. **Execute**:
   - Analyze code/requirements
   - Implement changes
   - Verify (tests/lint/typecheck)
5. **Complete**:
   - Sync beads (`br sync --flush-only`, `git add .beads/`, `git commit`)
   - Release reservations (`release_file_reservations`)
   - Close task (`br close <ID>`)
   - Announce completion on Agent Mail

## Detailed Steps

### 1. Initialization
- **Read Instructions**: `AGENTS.md` and `README.md`.
- **Understand Codebase**: Use `finder`, `Read`, `glob` to map architecture.
- **Register**:
  - `ensure_project(human_key=cwd)`
  - `register_agent(project_key=cwd, program="amp", model="...", task_description="Worker")`
  - `fetch_inbox` (check for existing context)
  - `send_message` (Intro to "All Agents")

### 2. Task Selection (The "Beads" Way)
- **Do NOT guess**. Use `bv` (Beads Viewer) robotics.
- Run: `bv --robot-triage`
- Look at `.quick_ref.top_picks` or `.recommendations`.
- Pick the first actionable item that matches your capabilities.

### 3. Claiming & Coordination
- **File Reservations**:
  - `file_reservation_paths(project_key, agent_name, paths=["src/module/**"], reason="br-123")`
- **Agent Mail**:
  - `send_message(project_key, sender_name, to=["Team"], subject="[br-123] Starting task...", thread_id="br-123")`
  - *Note*: Always use the bead ID (e.g., `br-123`) as the `thread_id`.

### 4. Execution & Quality
- **Investigate**: `finder` or `Read` relevant files.
- **Plan**: Use `oracle` for complex changes.
- **Implement**: `edit_file` / `create_file`.
- **Verify**: Run tests (`pytest`, `npm test`) and linters as defined in `AGENTS.md`.

### 5. Completion & Handoff
- **Close Bead**:
  - `br close br-123 --reason "Completed"`
  - `br sync --flush-only`
  - `git add .beads/`
  - `git commit -m "Complete br-123"`
- **Release Locks**:
  - `release_file_reservations(project_key, agent_name)`
- **Notify**:
  - `send_message(..., thread_id="br-123", body_md="Task completed. Summary: ...")`
- **Handoff (Critical)**:
  - Call the `handoff` tool to reset context and continue working.
  - Set `goal="Load the worker-agent skill and proceed to the next highest priority bead."`.
  - Set `follow=true`.
  - *Never* continue working in the same thread after finishing a substantial task. Fresh context ensures reliability.

## Communication Guidelines
- **Be Proactive**: Don't wait for orders if tasks are in the queue.
- **Be Explicit**: "I am starting task X." "I am blocked by Y."
- **Avoid Purgatory**: If no reply in reasonable time, proceed with best judgment or pick a different task.
- **Check Inbox**: Regularly call `fetch_inbox` to see new instructions.

## Tools Reference
- **br (Beads Rust)**:
  - `br ready`: List actionable tasks
  - `br list`: List all tasks
  - `br show <ID>`: Details
  - `br update <ID> ...`: Modify state
- **bv (Beads Viewer)**:
  - `bv --robot-triage`: The brain.
