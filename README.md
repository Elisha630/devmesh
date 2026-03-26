# DevMesh — Multi-Agent Orchestration Framework

## 🎯 Overview

DevMesh is a local multi-agent orchestration system that coordinates multiple AI CLI tools (Claude, Gemini, Ollama, etc.) to work together on tasks. It provides:

- **WebSocket Coordinator** — Single source of truth for all agent activity
- **Live Dashboard** — Real-time visualization of tasks, agents, and locks
- **Lock Management** — READ/WRITE/INTENT/CO_WRITE semantics for safe collaboration
- **Hardware Throttling** — Resource limits (GPU/RAM) enforced per agent
- **Audit Logging** — Complete event history for debugging and compliance

## 📁 Project Structure

```
DevMesh/
├── server.py              # Main orchestration server
├── agent_bridge.py        # CLI tool wrapper (registers agents with server)
├── client_mock.py         # Test client for development
├── dashboard.html         # Web UI (static asset, served by server)
├── config.py              # Configuration management (NEW)
├── logger.py              # Structured logging (NEW)
├── errors.py              # Custom exception hierarchy (NEW)
└── .devmesh/
    └── audit.jsonl        # Event audit log
```

## 🚀 Quick Start

### Server
```bash
cd DevMesh
python server.py
```
Opens browser at `http://127.0.0.1:7701`

### Connect an Agent
```bash
python agent_bridge.py --tool claude --ws ws://127.0.0.1:7700
```

### Available Tools
- `claude`, `gemini`, `codex`, `aider`, `continue`, `cody`, `cursor`, `ollama`, `sgpt`, `gh`

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

## 📊 Architecture

### Event Flow
1. **Agent Registration** — AI tool connects, declares resources and capabilities
2. **Task Creation** — Dashboard broadcasts task instruction to all agents
3. **Lock Management** — Agents request locks before reading/writing files
4. **Execution** — Agent runs CLI tool, captures output
5. **Completion** — Agent releases locks, reports results

### Lock Types
- **READ** — Multiple agents can read same file simultaneously
- **WRITE** — Exclusive lock; no other access allowed
- **INTENT** — Signals intent to write; prevents other INTENT locks
- **CO_WRITE** — Pair programming mode; multiple writers collaborate

### Task States
```
QUEUED → CLAIMED → WORKING → COMPLETED
                 ↓
              FAILED/ABANDONED
```

## 🔧 Improvements (Recent)

### Configuration Management (`config.py`)
- **Centralized settings** — No hardcoded values
- **Environment variables** — Override any setting without code changes
- **Validation** — Automatic configuration validation
- **Shared tool definitions** — Single source of truth for CLI tools

### Structured Logging (`logger.py`)
- **Color-coded console output** — Easy on the eyes in development
- **Optional file logging** — For production debugging
- **Configurable levels** — DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Replaces scattered print()** — Better trace and profiling

### Error Handling (`errors.py`)
- **Custom exception hierarchy** — Specific errors for each domain
- **Structured error responses** — JSON-serializable error details
- **Better debugging** — Error codes, context, and suggested actions

### Dashboard Extraction
- **Separated HTML from server code** — Easier maintenance
- **Cleaner server logic** — ~200 fewer lines in server.py
- **Can be cached/versioned** — Static asset instead of generated

## 🎓 Design Patterns

### Rulebook (Rules 1-10)
DevMesh enforces a set of rules to ensure safe multi-agent collaboration:

1. **Framework Authority** — First agent becomes ARCHITECT
3. **No Task Assignment** — Agents bid fairly; server arbitrates
4. **Lock Hierarchy** — INTENT → WRITE → READ with clear semantics
5. **Heartbeat Obligation** — Keep-alive signals or auto-release lock
6. **Critic Requirement** — Code review by second agent if flagged
7. **Hardware Throttle** — Respect GPU/RAM limits globally
8. **Read Before Work** — Non-ARCHITECT agents read framework first
9. **Diff-Based Writes** — Track file changes, prevent duplicates
10. **Pub/Sub File Events** — Real-time change notifications

## 📈 TODO / Future Work

- [ ] Persistent task storage (SQLite/PostgreSQL)
- [ ] Agent recovery on connection loss
- [ ] Task priority queuing and scheduling
- [ ] Dashboard streaming WebSocket optimization
- [ ] Role-based access control (ARCHITECT-only commands)
- [ ] Performance profiling and metrics
- [ ] Docker containerization
- [ ] Kubernetes operator support
- [ ] Integration with git for file versioning
- [ ] Slack/Discord notifications

## 🧪 Testing

Run mock client for development:
```bash
python client_mock.py --model architect
python client_mock.py --model agent1
```

## 📝 License

MIT

## 🤝 Contributing

1. Follow PEP 8 style guidelines
2. Add type hints to new functions
3. Update README with significant changes
4. Ensure logging replaces print() statements
