"""
Integration Guide: All Fixes for DevMesh Issues
================================================

This guide shows how to integrate all the newly created modules and features
into the existing DevMesh codebase to address the 5 main issues.

## Issue #1: Error Handling & Resilience

### Before (Broad Exception Handling)
```python
async def _handle_message(self, ws, message: str):
    try:
        data = orjson.loads(message)
    except Exception as e:  # TOO BROAD!
        await ws.send(orjson.dumps({"event": "error", "reason": "invalid_json"}))
        return
```

### After (Specific Exception Handling with Structured Logging)
```python
from error_handler import get_error_handler, ErrorSeverity

error_handler = get_error_handler()

async def _handle_message(self, ws, message: str):
    try:
        data = orjson.loads(message)
    except (ValueError, TypeError) as e:
        error_handler.handle(
            error=e,
            source="agent_handler.message_parse",
            handler_name="_handle_message",
            context_data={"message_length": len(message)},
            severity=ErrorSeverity.WARNING,
        )
        await ws.send(orjson.dumps({"event": "error", "reason": "invalid_json"}))
        return
    except Exception as e:
        error_handler.handle(
            error=e,
            source="agent_handler.message_parse",
            severity=ErrorSeverity.ERROR,
        )
        return
```

### In server.py __init__:
```python
# Initialize error handler with dashboard callback
from error_handler import init_error_handler
error_handler = init_error_handler(cfg.audit_log_dir)
error_handler.register_callback(self._on_error)

async def _on_error(self, error_ctx):
    # Push errors to dashboard
    await self._push_dash({
        "type": "error",
        "data": error_ctx.to_dict()
    })
```

## Issue #2: Configuration System

### Using the New Config Manager
```python
from config_manager import get_config_manager, init_config_manager
from pathlib import Path

# Initialize at startup
cfg_manager = init_config_manager(config_dir=Path(os.getcwd()))

# Access config
server_cfg = cfg_manager.server_config
print(f"ws_port={server_cfg.ws_port}")
print(f"cache_ttl={server_cfg.cache_ttl_sec}")

# Get per-tool config
tool_config = cfg_manager.get_tool_config("claude")
if tool_config:
    print(f"Model enabled: {tool_config.enabled}")
    print(f"Webhook URL: {tool_config.webhook_url}")

# Watch for reload events
def on_config_reload(manager):
    print("Config reloaded!")

cfg_manager.watch("dashboard", on_config_reload)

# Runtime reload
cfg_manager.reload()
```

### Configuration Files (devmesh.yaml)
```yaml
ws_host: 127.0.0.1
ws_port: 7700
ws_ping_interval_sec: 30
ws_ping_timeout_sec: 10

enable_result_caching: true
cache_ttl_sec: 3600
cache_max_size_mb: 100

enable_webhooks: true
enable_file_watching: true
enable_task_templates: true

log_level: INFO
```

### Per-tool Configuration (tools.yaml)
```yaml
tools:
  claude:
    enabled: true
    max_concurrent: 1
    timeout_sec: 120
    webhook_url: "https://example.com/webhook/claude"
    custom_env:
      CLAUDE_API_KEY: "${env:CLAUDE_API_KEY}"
  
  gpt4:
    enabled: true
    max_concurrent: 2
    timeout_sec: 180
```

## Issue #3: Dashboard UI Enhancements

### Adding to dashboard.html
```html
<!-- Add to <head> section -->
<script src="dashboard_enhancements.js"></script>

<!-- Add to CSS section-->
<style>
  /* Copy ENHANCED_STYLES from dashboard_enhancements.js */
</style>

<!-- Add search bar before task list -->
<div class="search-bar">
  <input id="task-search" placeholder="Search tasks..." onkeyup="taskManager.setSearchTerm(this.value)"/>
  <span style="padding:6px 0;color:var(--mu)">|</span>
  <div style="padding:6px 0;display:flex;gap:4px;flex-wrap:wrap">
    <span class="filter-badge" onclick="taskManager.toggleFilter('completed')">✓ Completed</span>
    <span class="filter-badge" onclick="taskManager.toggleFilter('working')">⚡ Working</span>
    <span class="filter-badge" onclick="taskManager.toggleFilter('queued')">📋 Queued</span>
    <span class="filter-badge" onclick="taskManager.toggleFilter('failed')">✗ Failed</span>
  </div>
</div>

<!-- Metrics displays -->
<div id="metrics-container" class="metrics-container">
  <div class="metrics-title">Execution Metrics</div>
  <canvas id="execution-rate-graph" class="metric-graph"></canvas>
  <canvas id="success-rate-graph" class="metric-graph"></canvas>
</div>
```

### Toggle Metrics View
```javascript
function toggleMetrics() {
  document.getElementById('metrics-container').classList.toggle('shown');
  metricsCollector.drawExecutionGraph('execution-rate-graph');
  metricsCollector.drawSuccessRateGraph('success-rate-graph');
}
```

## Issue #4: Features Implementation

### Result Caching
```python
from services.result_cache import get_cache

cache = get_cache(max_size_mb=100, default_ttl_sec=3600)

# Cache a result
def execute_task(task_id, params):
    # Check cache first
    cached = cache.get(task_id, params)
    if cached:
        return cached
    
    # Execute task...
    result = run_task(task_id, params)
    
    # Cache result
    cache.set(task_id, result, params=params, ttl_sec=3600)
    return result

# Invalidate cache
cache.invalidate(task_id)

# Get stats
print(cache.get_stats())
# {'hits': 42, 'misses': 15, 'hit_rate': '73.7%', ...}
```

### Webhook Notifications
```python
from services.webhook_manager import get_webhook_manager, WebhookEvent

webhook_mgr = get_webhook_manager()

# Register endpoints
webhook_mgr.register_webhook(
    webhook_id="slack",
    url="https://hooks.slack.com/services/...",
    events=[WebhookEvent.TASK_COMPLETED, WebhookEvent.TASK_FAILED],
)

# Fire events
await webhook_mgr.fire(
    WebhookEvent.TASK_COMPLETED,
    data={
        "task_id": "task_123",
        "status": "completed",
        "duration_sec": 42.5,
    }
)
```

### Task Templates
```python
from services.task_templates import get_template_manager

template_mgr = get_template_manager()

# List built-in templates
templates = template_mgr.list_templates()

# Create task from template
task_dict = template_mgr.create_task_from_template(
    template_id="code_review",
    bindings={"path": "src/main.py", "focus": "security"}
)

# Register custom template
custom_template = TaskTemplate(
    template_id="custom_audit",
    name="Security Audit",
    description="Perform security audit",
    description_template="Audit {module} for security vulnerabilities in {area}",
    variables={
        "module": {"required": True},
        "area": {"description": "Security area to focus on"},
    }
)
template_mgr.register_template(custom_template)
```

### File Watching
```python
from services.file_watcher import get_file_watcher

watcher = get_file_watcher(debounce_sec=1.0)

async def on_files_changed(events):
    for event in events:
        print(f"{event.path} - {event.change_type}")

watcher.watch("/home/user/project", callback=on_files_changed)

# Start watching
await watcher.start()

# Stop when done
await watcher.stop()
```

## Issue #5: Performance & Monitoring

### WebSocket Health Monitoring
```python
from services.ws_health import get_health_monitor

health_monitor = get_health_monitor(ping_interval=30.0, ping_timeout=10.0)

# Register a connection
async def on_agent_connect(ws):
    health = health_monitor.register_connection(client_id=ws.remote_address[0])
    await health.start_pinging()
    
    # In message handler
    async def on_message(msg):
        health.on_message()

# On pong received
def on_pong(ws):
    client_id = ws.remote_address[0]
    health = health_monitor.get_health(client_id)
    if health:
        health.on_pong_received()

# Check health periodically
async def health_check_loop():
    while True:
        await asyncio.sleep(60)
        await health_monitor.check_all_health()
        unhealthy = health_monitor.get_unhealthy_connections()
        if unhealthy:
            log.warning(f"Unhealthy connections: {unhealthy}")

# Get metrics
metrics = health_monitor.get_all_metrics()
for client_id, metrics in metrics.items():
    print(f"{client_id}: latency={metrics['latency_ms']:.1f}ms")
```

## Integration Example: Updated server.py __init__

```python
class DevMeshServer:
    def __init__(self):
        # ... existing code ...
        
        # NEW: Initialize configuration manager
        from config_manager import init_config_manager
        self.cfg_manager = init_config_manager()
        self.cfg = self.cfg_manager.server_config
        
        # NEW: Initialize error handler
        from error_handler import init_error_handler
        self.error_handler = init_error_handler(cfg.audit_log_dir)
        self.error_handler.register_callback(self._on_error)
        
        # NEW: Initialize services
        from services.result_cache import init_cache
        from services.webhook_manager import get_webhook_manager
        from services.task_templates import get_template_manager
        from services.file_watcher import get_file_watcher
        from services.ws_health import get_health_monitor
        
        self.cache = init_cache(
            self.cfg.cache_max_size_mb,
            self.cfg.cache_ttl_sec
        )
        self.webhooks = get_webhook_manager()
        self.templates = get_template_manager()
        self.file_watcher = get_file_watcher()
        self.health_monitor = get_health_monitor(
            self.cfg.ws_ping_interval_sec,
            self.cfg.ws_ping_timeout_sec
        )
        
        # Start services
        if self.cfg.enable_file_watching:
            asyncio.create_task(self.file_watcher.start())
        
        if self.cfg.enable_result_caching:
            asyncio.create_task(self._cache_cleanup_loop())
        
        asyncio.create_task(self._health_check_loop())

    async def _on_error(self, error_ctx):
        """Called when error handler records an error."""
        await self._push_dash({
            "type": "error",
            "data": error_ctx.to_dict()
        })
    
    async def _cache_cleanup_loop(self):
        """Periodically clean up expired cache entries."""
        while True:
            await asyncio.sleep(300)
            removed = self.cache.cleanup_expired()
            if removed > 0:
                log.info(f"Cleaned up {removed} expired cache entries")
    
    async def _health_check_loop(self):
        """Monitor WebSocket connection health."""
        while True:
            await asyncio.sleep(60)
            health_status = await self.health_monitor.check_all_health()
            # Log or alert on unhealthy connections
```

## Summary of Changes

✅ **Issue #1 - Error Handling**: error_handler.py with structured logging
✅ **Issue #2 - Configuration**: config_manager.py with Pydantic validation
✅ **Issue #3 - Dashboard**: dashboard_enhancements.js with search, graphs, export, theme
✅ **Issue #4 - Features**: 
  - services/result_cache.py
  - services/webhook_manager.py
  - services/task_templates.py
  - services/file_watcher.py
✅ **Issue #5 - Monitoring**: services/ws_health.py with ping/pong and health tracking

## Next Steps

1. Run: `pip install -r requirements.txt` to install new dependencies
2. Update server.py handlers to use specific exceptions (not broad except Exception)
3. Integrate services into server.py __init__ and handlers
4. Add search bar and UI enhancements to dashboard.html
5. Test all new features with provided examples
"""
