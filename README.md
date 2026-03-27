# DevMesh — Multi-Agent Orchestration Framework

[![Tests](https://img.shields.io/badge/tests-13%20passed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.12+-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

## 🎯 Overview

DevMesh is a local multi-agent orchestration system that coordinates multiple AI CLI tools (Claude, Gemini, Ollama, etc.) to work together on tasks. It provides:

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
- Install dependencies: `pip install -r requirements.txt`

### Start the Server
```bash
python server.py
```
The dashboard will automatically open at `http://127.0.0.1:7701`

### Available Tools

DevMesh supports the following AI CLI tools (auto-detected from PATH):
- `claude` — Anthropic Claude
- `gemini` — Google Gemini
- `codex` — OpenAI Codex
- `aider` — Aider pair programming
- `continue` — Continue IDE extension
- `cody` — Sourcegraph Cody
- `cursor` — Cursor Agent CLI (headless via `--print`)
- `ollama` — Local LLM runner
- `sgpt` — Shell GPT
- `gh` — GitHub Copilot CLI

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

## 🔧 Core Components

### Configuration Management (`config.py`)
- **Centralized settings** — All configuration in one place
- **Environment variables** — Override any setting via `DEVMESH_*` env vars
- **Validation** — Automatic validation (e.g., port range 1-65535)
- **Type hints** — Full type annotations for IDE support

### Structured Logging (`logger.py`)
- **Color-coded console output** — Easy to read during development
- **Optional file logging** — Persist logs for production debugging
- **Configurable levels** — DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Contextual info** — Timestamps, module names, and log levels

### Error Handling (`errors.py`)
- **Custom exception hierarchy** — `DevMeshError` base class with specific subclasses
- **Structured error responses** — JSON-serializable with error codes
- **Better debugging** — Context, suggestions, and stack traces

### Storage Layer (`storage.py`)
- **SQLite storage** — Persistent tasks, agents, projects, and audit log
- **Audit logging** — Events written to `.devmesh/devmesh.db` and mirrored to `.devmesh/audit.jsonl`
- **Thread-safe operations** — Safe concurrent access with a write queue

### Dashboard (`dashboard.html`)
- **Real-time updates** — WebSocket-driven live visualization
- **Task management** — Create, monitor, and manage tasks
- **Lock visualization** — See which agents hold which locks
- **Agent status** — Monitor connected agents and their resources

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

## 📈 TODO / Future Work

- [ ] Optional PostgreSQL backend
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

Run the test suite:
```bash
pytest tests/ -v
```

Run mock clients for development:
```bash
python client_mock.py --model architect
python client_mock.py --model agent1
```

## 📝 License

MIT License — See [LICENSE](LICENSE) for details.

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. **Code Style** — Follow PEP 8 style guidelines
2. **Type Hints** — Add type annotations to all new functions
3. **Documentation** — Update README with significant changes
4. **Logging** — Use the `logger` module instead of `print()` statements
5. **Testing** — Add tests for new functionality in `tests/test_core.py`
6. **Commit Messages** — Write clear, descriptive commit messages

### Development Workflow

```bash
# Clone and setup
git clone <repository-url>
cd DevMesh
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Run server
python server.py

# Connect test agents
python client_mock.py --model architect
python client_mock.py --model agent1
```
