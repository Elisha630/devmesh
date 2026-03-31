"""
DevMesh Fixes - Quick Reference & Integration Checklist
=======================================================

This is a quick reference guide for integrating all the fixes.

## 🚀 QUICK START (15 minutes)

### 1. Install New Dependencies (2 min)
​```bash
cd /home/zer0day/StudioProjects/devmesh
pip install pydantic pyyaml httpx watchfiles
# Or: pip install -r requirements.txt
​```

### 2. Review New Files (3 min)
- error_handler.py - Error handling with structured logging
- config_manager.py - Configuration with Pydantic validation
- services/result_cache.py - LRU cache for task results
- services/webhook_manager.py - Webhook notifications
- services/task_templates.py - Task templates system
- services/file_watcher.py - Real file system watching
- services/ws_health.py - WebSocket health monitoring
- dashboard_enhancements.js - Dashboard UI improvements

### 3. Key Integration Points (10 min)
See INTEGRATION_GUIDE.md for detailed examples.

---

## 📋 INTEGRATION CHECKLIST

### Phase 1: Error Handling (Priority: HIGH)
```python
# In server.py, around line 1, add:
from error_handler import init_error_handler, ErrorSeverity

# In server.__init__():
self.error_handler = init_error_handler(cfg.audit_log_dir)
self.error_handler.register_callback(self._on_error)

async def _on_error(self, error_ctx):
    await self._push_dash({
        "type": "error",
        "data": error_ctx.to_dict()
    })
```

**Then update all handlers**:
- handlers/agent_handler.py: ~3 except blocks
- handlers/dashboard_handler.py: ~2 except blocks  
- server.py: ~14 except blocks
- Replace `except Exception` with specific types
- Call `self.error_handler.handle(e, source, ...)`

### Phase 2: Configuration System (Priority: HIGH)
```python
# In server.py __init__:
from config_manager import init_config_manager
self.cfg_manager = init_config_manager()
self.cfg = self.cfg_manager.server_config

# Remove old config.py initialization
# Use self.cfg instead of cfg module
```

**Test with**:
```bash
# Set env var
export DEVMESH_WS_PORT=7700
export DEVMESH_ENABLE_RESULT_CACHING=true

# Or create devmesh.yaml:
cat > devmesh.yaml << EOF
ws_port: 7700
enable_result_caching: true
cache_ttl_sec: 3600
EOF
```

### Phase 3: Services Integration (Priority: MEDIUM)
```python
# In server.__init__():
from services.result_cache import init_cache
from services.webhook_manager import get_webhook_manager
from services.task_templates import get_template_manager
from services.file_watcher import get_file_watcher
from services.ws_health import get_health_monitor

self.cache = init_cache(cfg.cache_max_size_mb, cfg.cache_ttl_sec)
self.webhooks = get_webhook_manager()
self.templates = get_template_manager()
self.file_watcher = get_file_watcher()
self.health_monitor = get_health_monitor(cfg.ws_ping_interval_sec, cfg.ws_ping_timeout_sec)

# Start async services
asyncio.create_task(self.file_watcher.start())
asyncio.create_task(self._cache_cleanup_loop())
asyncio.create_task(self._health_check_loop())
```

### Phase 4: WebSocket Health (Priority: MEDIUM)
```python
# In agent_handler.py _handle():
# Register connection
health = self.server.health_monitor.register_connection(client_id)
await health.start_pinging()

# When message received
health.on_message()

# When pong received
health.on_pong_received()

# On error
health.on_error()
```

### Phase 5: Dashboard Enhancements (Priority: LOW)
```html
<!-- In dashboard.html, add to <head>: -->
<script src="dashboard_enhancements.js"></script>

<!-- Add to CSS section (copy from dashboard_enhancements.js) -->

<!-- Before task list, add: -->
<div class="search-bar">
  <input id="task-search" placeholder="Search tasks..." 
         onkeyup="taskManager.setSearchTerm(this.value)"/>
  <div style="display:flex;gap:4px">
    <span class="filter-badge" onclick="taskManager.toggleFilter('completed')">✓ Completed</span>
    <span class="filter-badge" onclick="taskManager.toggleFilter('working')">⚡ Working</span>
  </div>
</div>

<!-- In header, add theme toggle and export menu -->
```

---

## 🔄 INTEGRATION FLOW

```
Step 1: Install dependencies
   ↓
Step 2: Add error_handler to server.__init__
   ↓
Step 3: Replace exception handlers (most time-consuming)
   ↓
Step 4: Initialize config_manager
   ↓
Step 5: Initialize services (cache, webhooks, templates, watcher, health)
   ↓
Step 6: Hook up WebSocket health monitoring
   ↓
Step 7: Add dashboard UI enhancements
   ↓
Step 8: Test all features
```

---

## ⚡ SPECIFIC CODE LOCATIONS TO MODIFY

### server.py
- **Line ~100**: Add imports for new services
- **Line ~400**: Add initialization of services in __init__
- **~12 locations**: Replace `except Exception` blocks with specific types
- **New methods**: _cache_cleanup_loop(), _health_check_loop(), _on_error()

### handlers/agent_handler.py
- **Line ~5**: Add error_handler import
- **Line ~42**: Replace `except Exception as e:`
- **Line ~302**: Replace `except Exception:`
- **In handle()**: Register connection health monitoring
- **In _handle_message()**: Call health.on_message()

### handlers/dashboard_handler.py
- **Line ~45**: Replace `except Exception as e:`
- Similar pattern to agent_handler.py

### dashboard.html
- **Head section**: Add script import for dashboard_enhancements.js
- **CSS section**: Add enhanced styles
- **Main content**: Add search bar and filter badges
- **Headers**: Add theme toggle and export buttons

---

## 🧪 TESTING AFTER INTEGRATION

```bash
# 1. Test error handling
# Force an error and check error_handler.jsonl

# 2. Test configuration
export DEVMESH_WS_PORT=7999
python server.py  # Should start on port 7999

# 3. Test cache
# Task the same thing twice quickly
# Check cache.get_stats() shows hits

# 4. Test webhooks
# Register a test webhook endpoint
# Complete a task
# Check webhook was called

# 5. Test file watching
# Create/modify a file in watched directory
# Check file_change events

# 6. Test WebSocket health
# Check WebSocket connections have latency metrics
# Forcefully disconnect and check recovery

# 7. Test dashboard
# Try search filter
# Try export
# Try theme toggle
```

---

## 📊 ESTIMATED EFFORT

| Task | Effort | Time |
|------|--------|------|
| Install dependencies | 1 min | 1 min |
| Add error_handler | 30 min | 30-45 min |
| Replace exception handlers | 60 min | 60-90 min |
| Add config_manager | 15 min | 15-30 min |
| Initialize services | 20 min | 20-30 min |
| Hook WebSocket health | 20 min | 20-30 min |
| Dashboard enhancements | 30 min | 30-45 min |
| Testing | 30 min | 30-45 min |
| **TOTAL** | **3.5 hours** | **4-5 hours** |

---

## ⚠️ IMPORTANT NOTES

1. **Backward Compatibility**: All new services have fallbacks if dependencies missing
2. **Breaking Changes**: No breaking changes to existing APIs
3. **Testing**: Unit tests for new services included (see tests/ directory)
4. **Performance**: All new services are lightweight and async-friendly
5. **Logging**: All new modules log to standard Python logging

---

## 🎯 SUCCESS CRITERIA

After integration, you should have:

✅ Structured error logging to JSONL with dashboard display
✅ Configuration system supporting YAML/TOML and env vars
✅ Result caching with LRU eviction and TTL
✅ Webhook notifications for task events
✅ Task templating system
✅ Real file watching with debounce
✅ WebSocket health monitoring with latency tracking
✅ Dashboard search/filter functionality
✅ Task export to JSON/CSV/TSV
✅ Light/dark theme toggle
✅ Mobile-responsive UI

---

## 💬 QUESTIONS?

Each module includes:
- Full docstrings
- Type hints
- Usage examples
- Error handling

See INTEGRATION_GUIDE.md for detailed examples.
See IMPLEMENTATION_SUMMARY.md for complete overview.

---
"""
