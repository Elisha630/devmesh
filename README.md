# DevMesh — Multi-Agent Orchestration Framework

[![Tests](https://img.shields.io/badge/tests-13%20passed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.12+-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

## 🎯 Overview

DevMesh is a **local multi-agent orchestration framework** that lets you coordinate multiple AI CLI tools (Claude, Gemini, Codex, etc.) to work together autonomously on tasks.

### Why DevMesh?

- **Leverage Multiple AI Tools** — Use the best tool for each job (Claude for architecture, Codex for quick scripts, etc.)
- **Autonomous Coordination** — Agents work together without human intervention
- **Safe Collaboration** — Lock system prevents agents from stepping on each other's toes
- **Local & Fast** — No cloud dependencies, everything runs locally with WebSocket coordination
- **Observable** — Real-time dashboard shows what agents are doing, what they're accessing, and resource usage
- **Extensible** — Works with any AI CLI tool that accepts a prompt argument

### Core Concepts

**Agents** — AI CLI tools (Claude, Gemini, etc.) connected to DevMesh and ready to accept tasks

**Tasks** — Instructions broadcast to all agents; agents bid fairly to claim work

**Locks** — File access control system (READ/WRITE/INTENT/CO_WRITE) to prevent conflicts

**Hardware Throttling** — GPU/RAM limits enforced globally to prevent resource exhaustion

**Rulebook** — 10 design principles that ensure safe multi-agent collaboration

### Key Features

- **WebSocket Coordinator** — Single source of truth for all agent activity
- **Live Dashboard** — Real-time visualization of tasks, agents, and locks
- **Lock Management** — READ/WRITE/INTENT/CO_WRITE semantics for safe collaboration
- **Hardware Throttling** — Resource limits (GPU/RAM) enforced per agent
- **Audit Logging** — Event history persisted to SQLite and JSONL
- **Configuration Management** — Environment-based settings with validation
- **Structured Logging** — Color-coded console output with optional file logging

## 📁 Project Structure

```
.
├── server.py              # Main orchestration server (WebSocket + HTTP)
├── agent_bridge.py        # CLI tool wrapper (registers agents with server)
├── client_mock.py         # Test client for development/testing
├── dashboard.html         # Web UI (static asset, served by server)
├── config.py              # Configuration management & validation
├── logger.py              # Structured logging with colored output
├── errors.py              # Custom exception hierarchy
├── storage.py             # SQLite storage + audit logging
├── check_tools.py         # Utility to verify available CLI tools
├── requirements.txt       # Python dependencies
├── tests/
│   └── test_core.py       # Unit tests
└── .devmesh/
    ├── audit.jsonl        # Event audit log (JSONL mirror)
    └── devmesh.db         # SQLite persistence (tasks, agents, audit, projects)
```

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- At least one AI CLI tool installed (Claude, Cursor Agent, Gemini, Codex, etc.)
- Install dependencies: `pip install -r requirements.txt`

### Start the Server
```bash
python server.py
```
The dashboard will automatically open at `http://127.0.0.1:7701` and the server listens on `ws://127.0.0.1:7700` for agent connections.

### Supported AI Tools

DevMesh automatically detects and works with the following AI CLI tools (in order of precedence):

| Tool | Command | Invoke Mode | Best For |
|------|---------|-------------|----------|
| **Claude (via agent CLI)** | `claude` | arg | Code generation, refactoring |
| **Cursor Agent** | `agent` | arg | Agentic tasks with native trust |
| **Google Gemini** | `gemini` | arg | Multi-modal tasks |
| **OpenAI Codex** | `codex` | arg | Code completion, shell commands |
| **Aider** | `aider` | stdin | Pair programming, collaborative editing |
| **Continue** | `continue` | arg | IDE-integrated development |
| **Sourcegraph Cody** | `cody` | arg | Code search & understanding |
| **Ollama** | `ollama` | arg | Local LLM inference |
| **ShellGPT** | `sgpt` | arg | Shell scripting assistance |
| **GitHub Copilot** | `gh` | arg | GitHub-integrated suggestions |

All tools run in **non-interactive mode** (YOLO/auto-approve) to enable fully autonomous operation.

## ⚙️ Configuration

All settings can be overridden via environment variables:

```bash
# Server
export DEVMESH_WS_HOST=127.0.0.1
export DEVMESH_WS_PORT=7700
export DEVMESH_HTTP_PORT=7701
export DEVMESH_DASHBOARD_PORT=7702

# Hardware
export DEVMESH_GPU_VRAM_GB=16
export DEVMESH_RAM_GB=32

# Timeouts
export DEVMESH_LOCK_TTL_SEC=15
export DEVMESH_HEARTBEAT_GRACE_SEC=5

# Logging
export DEVMESH_LOG_LEVEL=INFO
export DEVMESH_LOG_FILE=logs/devmesh.log
```

See [config.py](config.py) for all available settings.

## 📊 How It Works

### Event Flow
1. **Server Startup** — WebSocket listeners start; Dashboard opens in browser
2. **Agent Registration** — Agent CLI connects, declares tool name and resource requirements
3. **Tool Detection** — Server checks if agent command is available in PATH
4. **Task Broadcast** — User sends task from dashboard; server broadcasts to all connected agents
5. **Lock Negotiation** — Agents request locks (READ/WRITE/INTENT/CO_WRITE) before accessing files
6. **Execution** — Agent runs CLI tool with task prompt; captures structured JSON output
7. **Results Collection** — Agent reports completion, release locks; results stored in audit log
8. **Display** — Dashboard updates in real time with results, logs, and hardware metrics

### Lock Management System

The lock system prevents conflicts when multiple agents access the same files:

- **READ** — Multiple agents can hold simultaneously; blocks WRITE/INTENT
- **WRITE** — Exclusive access; only one agent at a time
- **INTENT** — Signal that you'll write soon; blocks other INTENT locks  
- **CO_WRITE** — Pair programming mode; multiple agents can write collaboratively

### Task Lifecycle

```
┌─────────┐
│ QUEUED  │ Task created, waiting for agent to claim
└────┬────┘
     │
     ↓
┌─────────┐
│ CLAIMED │ Agent has accepted the task
└────┬────┘
     │
     ↓
┌─────────┐
│ WORKING │ Agent is executing the task
└────┬────┘
     │
     +─────────────────────────┐
     ↓                         ↓
┌──────────┐            ┌──────────┐
│COMPLETED │            │  FAILED  │
└──────────┘            └──────────┘
     ↑
     └─┬──────────────────────┐
       ↓                      ↓
┌──────────────┐         ┌─────────────┐
│  ABANDONED   │         │  PAUSED *   │
└──────────────┘         └─────────────┘
     
* PAUSED: Not fully implemented yet (reserved for future use)
```

### Hardware Resource Tracking

Each agent declares its resource needs (VRAM, RAM). The server tracks allocation:

- **Allocation Request** — Agent requests GPU/RAM; server checks available capacity
- **Grant or Deny** — If capacity available, allocate. Otherwise reject with available resources
- **Release** — When agent disconnects or task completes, resources freed automatically
- **Global Limits** — All allocations checked against system-wide GPU/RAM limits (env-configurable)

## 🔧 Implementation Details

### Server (`server.py`)
- **WebSocket Server** — Listens on `ws://127.0.0.1:7700` for agent connections
- **HTTP Server** — Serves dashboard and provides REST API endpoints on `:7701`
- **Dashboard WebSocket** — Separate connection on `:7702` for real-time UI updates
- **State Management** — Maintains authoritative state for agents, tasks, locks, and hardware
- **Lock Arbitration** — Implements lock request handling with conflict resolution
- **Heartbeat Monitor** — Tracks agent activity; auto-releases locks on timeout

### Agent Bridge (`agent_bridge.py`)
- **CLI Wrapper** — Wraps any AI CLI tool for DevMesh integration
- **Resource Declaration** — Reports tool name, capabilities, and resource requirements
- **Task Execution** — Receives tasks via WebSocket, runs CLI tool with task prompt
- **Lock Requests** — Negotiates file locks with server before accessing files
- **Structured Output** — Parses tool output, captures stdout/stderr, reports results

### Dashboard (`dashboard.html`)
- **Real-Time UI** — Live task list, agent status, lock visualization
- **Task Command Center** — Text input for broadcasting tasks to all agents
- **Hardware Monitor** — Graphs GPU/RAM usage over time
- **Event Log** — Raw stdout/stderr output and structured event stream
- **Knowledge Base** — RAG discoveries shared across agents

### Storage Layer (`storage.py`)
- **Task Persistence** — SQLite `tasks` table with full task metadata
- **Agent Registry** — Persistent record of connected agents, capabilities, resources
- **Audit Logging** — Every event (lock request, task completion, etc.) logged to `.devmesh/audit.jsonl`
- **Thread-Safe Queue** — Write queue prevents concurrent SQLite access issues
- **Backup & Recovery** — Audit log mirrored to both SQLite and JSONL for durability

### Configuration (`config.py`)
- **Centralized Settings** — All environment variables and defaults in one place
- **Tool Profiles** — Command templates and capability declarations for each AI CLI tool
- **Type Validation** — Validates port ranges, file paths, resource limits on startup
- **Environment Override** — Any setting overrideable via `DEVMESH_*` environment variables
- **Tool Detection** — Lists all registered tools with their CLI commands and invoke modes

### Logging (`logger.py`)
- **Structured Output** — Timestamps, log levels, module names in every message
- **Color Coding** — Different colors for DEBUG (blue), INFO (green), WARN (yellow), ERROR (red)
- **File Output** — Optional file logging (set `DEVMESH_LOG_FILE`)
- **Readable Format** — Easy to scan during development and debugging

### Error Handling (`errors.py`)
- **Exception Hierarchy** — Base `DevMeshError` with specific subclasses for different scenarios
- **JSON Serialization** — All errors convertible to JSON for dashboard/API responses
- **Context Info** — Each error includes relevant context for debugging
- **Error Codes** — Structured codes (e.g., `TOOL_NOT_FOUND`, `LOCK_TIMEOUT`) for programmatic handling

## 🎓 Design Patterns

### Rulebook (Rules 1-10)

DevMesh enforces a set of rules to ensure safe multi-agent collaboration:

| # | Rule | Description |
|---|------|-------------|
| 1 | **Framework Authority** | First agent becomes ARCHITECT |
| 2 | **No Task Assignment** | Agents bid fairly; server arbitrates |
| 3 | **Lock Hierarchy** | INTENT → WRITE → READ with clear semantics |
| 4 | **Heartbeat Obligation** | Keep-alive signals or auto-release lock |
| 5 | **Critic Requirement** | Code review by second agent if flagged |
| 6 | **Hardware Throttle** | Respect GPU/RAM limits globally |
| 7 | **Read Before Work** | Non-ARCHITECT agents read framework first |
| 8 | **Diff-Based Writes** | Track file changes, prevent duplicates |
| 9 | **Pub/Sub File Events** | Real-time change notifications |
| 10 | **Single Source of Truth** | Server is authoritative state holder |

## 📈 What's Implemented

### Core Features ✅
- ✅ **WebSocket Coordinator** — Single source of truth for all agent activity, tasks, and locks
- ✅ **Live Dashboard** — Real-time web UI with task tracking, agent monitoring, and lock visualization
- ✅ **Lock Management** — READ/WRITE/INTENT/CO_WRITE semantics for safe collaboration between agents
- ✅ **Hardware Throttling** — Global GPU/RAM limits enforced per each agent connection
- ✅ **Audit Logging** — Complete event history persisted to SQLite and mirrored to JSONL
- ✅ **Configuration Management** — Environment-based settings with validation and defaults
- ✅ **Structured Logging** — Color-coded console output with optional file logging
- ✅ **Non-Interactive Mode** — All tools run with auto-approval flags for autonomous operation
- ✅ **Multi-Tool Support** — Works with 10+ different AI CLI tools via unified interface

### Still TODO (Potential Future Work)

These features are out of scope for the current release:
- PostgreSQL backend (SQLite is sufficient for most use cases)
- Kubernetes operator support (local orchestration is the focus)
- Slack/Discord bot notifications
- Git-based file versioning (can be added as a storage layer)
- Advanced performance profiling via Prometheus metrics

## 🧪 Testing & Development

### Run Tests
```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_core.py -v

# Run with coverage
pytest tests/ --cov=. --cov-report=term-missing
```

### Development Setup
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dev dependencies
pip install -r requirements.txt
pip install pytest pytest-cov

# Start server in debug mode
DEVMESH_LOG_LEVEL=DEBUG python server.py
```

### Testing with Mock Agents
```bash
# Terminal 1: Start server
python server.py

# Terminal 2: Connect a mock agent
python client_mock.py --model architect

# Terminal 3: Connect another agent
python client_mock.py --model agent1

# Terminal 4: Send tasks via dashboard at http://127.0.0.1:7701
```

### Checking Available Tools
```bash
python check_tools.py
```
Lists all AI CLI tools detected in your PATH and their versions.

## 📝 License

MIT License — See [LICENSE](LICENSE) for details.

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

### Before You Code
1. **Open an issue** — Describe the feature or bug you want to fix
2. **Get feedback** — Wait for maintainer feedback before large changes
3. **Check the Rulebook** — Understand the 10 design principles in the rulebook

### Code Style
- **Python 3.12+** — Use modern Python features (type hints, dataclasses, etc.)
- **PEP 8 Compliance** — Format code with `black` or `autopep8`
- **Type Hints** — All functions must have complete type annotations
- **Docstrings** — Document public functions and classes with docstrings
- **Immutability** — Prefer immutable data structures where possible

### Testing
- **Unit Tests** — Write tests for all new functions in `tests/`
- **Integration Tests** — Test interactions between components
- **Coverage** — Aim for 80%+ code coverage
- **Run Before PR** — Ensure all tests pass: `pytest tests/ -v`

### Documentation
- **README Updates** — Reflect changes to user-facing features
- **Inline Comments** — Explain complex logic with comments
- **Commit Messages** — Use descriptive messages (e.g., "fix: resolve lock timeout in agent bridge")
- **CHANGELOG** — Update any breaking changes

### PR Process
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit with clear messages
4. Push to your fork
5. Open a PR with description of changes
6. Address review feedback
7. Merge when approved
