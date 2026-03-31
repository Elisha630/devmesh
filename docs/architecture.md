# DevMesh Architecture Documentation

## Overview

DevMesh is a local multi-agent orchestration framework that coordinates multiple AI CLI tools to work together on software development tasks.

## System Context (C4 Level 1)

```mermaid
graph TB
    User[Developer<br/>Human User]

    subgraph DevMesh["DevMesh System"]
        Server[DevMesh Server]
        Dashboard[Web Dashboard]
    end

    subgraph AI_Agents["AI Agent Tools"]
        Claude[Claude Code]
        Cursor[Cursor]
        Gemini[Gemini CLI]
        Codex[OpenAI Codex]
        Aider[Aider]
    end

    subgraph Storage["Storage"]
        SQLite[(SQLite Database)]
        Audit[Audit Logs]
    end

    subgraph External["External Systems"]
        Prometheus[Prometheus]
        Files[File System]
    end

    User -->|"Web Browser"| Dashboard
    Dashboard -->|"WebSocket"| Server
    User -->|"IDE/Terminal"| AI_Agents

    Server -->|"WebSocket"| AI_Agents
    Server -->|"SQL"| SQLite
    Server -->|"JSON Lines"| Audit
    Server -->|"Read/Write"| Files
    Server -->|"Metrics"| Prometheus
```

## Container Diagram (C4 Level 2)

```mermaid
graph TB
    subgraph DevMesh_Server["DevMesh Server"]
        HTTP[HTTP Server<br/>Port 7701]
        Agent_WS[Agent WebSocket<br/>Port 7700]
        Dash_WS[Dashboard WebSocket<br/>Port 7702]

        subgraph Services["Business Logic"]
            AgentMgr[Agent Manager]
            TaskMgr[Task Manager]
            LockMgr[Lock Manager]
            ContextMgr[Context Manager]
        end

        Metrics[Prometheus Registry]
        Storage[Storage Manager]
    end

    Dashboard[Web Dashboard<br/>HTML/JS]

    subgraph AI_Tools["AI CLI Tools"]
        Agent1[Agent Bridge 1]
        Agent2[Agent Bridge 2]
    end

    subgraph Data["Data Storage"]
        SQLite[(SQLite)]
        AuditLog[Audit Log Files]
    end

    Dashboard -->|"ws://localhost:7702"| Dash_WS
    HTTP -->|"REST API"| Dashboard

    Agent1 -->|"ws://localhost:7700"| Agent_WS
    Agent2 -->|"ws://localhost:7700"| Agent_WS

    Agent_WS --> AgentMgr
    Dash_WS -->|"Commands"| Services

    AgentMgr -->|"CRUD"| Storage
    TaskMgr -->|"CRUD"| Storage
    LockMgr -->|"Events"| Storage
    ContextMgr -->|"Context"| Storage

    Storage -->|"SQL"| SQLite
    Storage -->|"Append"| AuditLog

    Services -->|"Counters/Gauges"| Metrics
```

## Component Diagram (C4 Level 3)

### Agent Manager

```mermaid
graph LR
    subgraph AgentManager["Agent Manager"]
        Registration[Registration Handler]
        Heartbeat[Heartbeat Monitor]
        RoleAssign[Role Assignment]
        HardwareAlloc[Hardware Allocator]
    end

    subgraph State["Agent State"]
        Agents[(Connected Agents)]
        Architect[(Architect Agent)]
    end

    WebSocket[WebSocket Handler]
    Storage[Storage Manager]
    Hardware[Hardware Throttle]

    WebSocket -->|"register"| Registration
    WebSocket -->|"heartbeat"| Heartbeat

    Registration -->|"New Agent"| RoleAssign
    Registration -->|"Allocate"| HardwareAlloc

    RoleAssign -->|"First Agent = Architect"| Architect
    Registration -->|"Persist"| Storage
    Heartbeat -->|"Update Status"| Agents
    HardwareAlloc -->|"VRAM/RAM"| Hardware
```

### Task Manager

```mermaid
graph LR
    subgraph TaskManager["Task Manager"]
        Queue[Task Queue]
        Priority[Priority Sorter]
        Lifecycle[Lifecycle Manager]
        Deps[Dependency Resolver]
    end

    subgraph TaskStates["Task States"]
        Queued[Queued]
        Claimed[Claimed]
        Working[Working]
        Completed[Completed]
    end

    API[WebSocket API]
    Storage[(Storage)]

    API -->|"create_task"| Queue
    API -->|"claim_task"| Lifecycle
    API -->|"complete_task"| Lifecycle

    Queue -->|"Sort by Priority"| Priority
    Priority -->|"Check Deps"| Deps
    Deps -->|"Ready"| Queued

    Lifecycle -->|"Transition"| TaskStates
    Lifecycle -->|"Persist"| Storage
```

### Lock Manager

```mermaid
graph LR
    subgraph LockManager["Lock Manager"]
        Conflict[Conflict Detector]
        Timeout[Timeout Manager]
        Heartbeat[Lock Heartbeat]
    end

    subgraph Locks["Active Locks"]
        ReadLocks[Read Locks]
        WriteLocks[Write Locks]
        IntentLocks[Intent Locks]
    end

    Agent_WS[Agent WebSocket]
    Broadcast[Broadcast Handler]

    Agent_WS -->|"lock_request"| Conflict
    Agent_WS -->|"lock_release"| LockManager

    Conflict -->|"Check"| Locks
    Conflict -->|"Granted"| Broadcast

    Timeout -->|"Expire"| Locks
    Heartbeat -->|"Refresh"| Locks
```

## Data Flow

### Task Creation Flow

```mermaid
sequenceDiagram
    participant User
    participant Dashboard
    participant Server
    participant Agent
    participant Storage

    User->>Dashboard: Enter task in chat
    Dashboard->>Server: WebSocket: chat message
    Server->>Server: Validate input
    Server->>Server: Create project folder
    Server->>Storage: Persist task
    Server->>Dashboard: Task created confirmation
    Server->>Agent: WebSocket: task_instruction
    Agent->>Server: WebSocket: task claim
    Server->>Storage: Update task status
    Server->>Dashboard: Broadcast: task claimed
```

### File Change Coordination

```mermaid
sequenceDiagram
    participant Agent1
    participant Server
    participant ContextMgr
    participant Agent2

    Agent1->>Server: file_change request
    Server->>ContextMgr: Update file context
    ContextMgr->>ContextMgr: Check for conflicts

    alt Conflict Detected
        ContextMgr->>Server: Conflict detected
        Server->>Agent2: file_changed notification
        Server->>Server: Trigger conflict resolution
    else No Conflict
        ContextMgr->>ContextMgr: Update version
        Server->>Agent2: file_changed notification
    end

    Server->>Agent1: file_change_ack
```

## Deployment Architecture

```mermaid
graph TB
    subgraph Single_Host["Single Host Deployment"]
        subgraph Docker["Docker Compose"]
            Server[DevMesh Server]
            Prometheus[Prometheus]
            Grafana[Grafana]
        end

        subgraph Host_System["Host System"]
            CLI_Tools[AI CLI Tools]
            FileSystem[Project Files]
        end
    end

    Browser[Web Browser]
    IDE[IDE/Editor]

    Browser -->|"HTTP 7701"| Server
    Browser -->|"WS 7702"| Server
    IDE -->|"WS 7700"| Server

    Server -->|"Execute"| CLI_Tools
    Server -->|"Read/Write"| FileSystem
    Server -->|"Metrics"| Prometheus
    Prometheus -->|"Visualize"| Grafana
```

## Technology Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12+ |
| Async Framework | asyncio, websockets |
| Database | SQLite with WAL mode |
| Serialization | orjson (fast JSON) |
| Metrics | Prometheus client |
| Web Server | http.server (built-in) |
| Dashboard | Vanilla HTML/JS |

## Scalability Considerations

1. **Single Node**: DevMesh is designed to run on a single developer workstation
2. **No Horizontal Scaling**: Not designed for multi-node deployment
3. **Resource Limits**: Hardware throttle prevents resource exhaustion
4. **Connection Limits**: Rate limiting prevents connection flooding

## Security Architecture

1. **Local Only**: By default, binds to 127.0.0.1 only
2. **No Authentication**: Assumes trusted local environment
3. **Input Validation**: All inputs sanitized before processing
4. **Path Traversal Protection**: File operations validated
5. **CORS**: Configured for local development
