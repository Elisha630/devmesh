# DevMesh Troubleshooting Guide

## Quick Diagnostics

Run the built-in health check:

```bash
curl http://localhost:7701/health | python -m json.tool
```

Check installed AI tools:

```bash
python check_tools.py
```

## Common Issues

### Server Won't Start

#### Port Already in Use

**Symptoms:**
```
OSError: [Errno 98] Address already in use
```

**Solutions:**
```bash
# Find process using port
lsof -i :7700
lsof -i :7701
lsof -i :7702

# Kill the process
kill -9 <PID>

# Or use different ports
export DEVMESH_WS_PORT=7703
export DEVMESH_HTTP_PORT=7704
export DEVMESH_DASHBOARD_PORT=7705
python server.py
```

#### Permission Denied

**Symptoms:**
```
PermissionError: [Errno 13] Permission denied
```

**Solutions:**
```bash
# Check directory permissions
ls -la .devmesh/

# Fix permissions
chmod 755 .devmesh/
chown $(whoami) .devmesh/
```

### Agents Can't Connect

#### Connection Refused

**Symptoms:**
```
Connection refused to ws://127.0.0.1:7700
```

**Check:**
1. Is server running?
   ```bash
   curl http://localhost:7701/health
   ```

2. Is firewall blocking?
   ```bash
   # Check if port is listening
   netstat -tlnp | grep 7700
   ```

3. Wrong host configuration?
   ```bash
   # Ensure DEVMESH_WS_HOST is set correctly
   export DEVMESH_WS_HOST=127.0.0.1
   ```

#### Agent Bridge Crashes

**Symptoms:**
- Agent process terminates immediately
- "Agent bridge failed" in dashboard chat

**Solutions:**
```bash
# Check if CLI tool is installed
which claude
which agent  # cursor
which gemini

# Check tool version
claude --version

# Run bridge manually for debugging
python agent_bridge.py --tool claude --ws ws://127.0.0.1:7700

# Check stderr log
cat /tmp/agent_bridge_*.log
```

### Tasks Not Being Processed

#### No Agents Connected

**Symptoms:**
- "No agents connected" message in dashboard
- Tasks stuck in "queued" state

**Solutions:**
```bash
# Check connected agents
curl http://localhost:7701/health | jq '.agents'

# Launch an agent from dashboard
# Or manually:
python agent_bridge.py --tool claude --ws ws://127.0.0.1:7700
```

#### Tasks Stuck in Queue

**Symptoms:**
- Tasks remain "queued" even with agents connected
- No task claim events

**Check:**
1. Are agents in "idle" status?
2. Check agent capabilities match task requirements
3. Verify task dependencies are satisfied

**Solutions:**
```bash
# Check agent status
curl http://localhost:7701/health | jq '.agents'

# Restart agent if stuck
# Stop and relaunch from dashboard
```

### Lock Conflicts

#### Lock Denied Errors

**Symptoms:**
```json
{"event": "lock_denied", "reason": "already_locked"}
```

**Solutions:**
1. Wait for current holder to release
2. Check which agent holds the lock in dashboard
3. Force disconnect if agent is stuck:
   ```bash
   # From dashboard: click "Disconnect" on agent
   # Or restart server (last resort)
   ```

#### Orphaned Locks

**Symptoms:**
- Files locked by disconnected agents
- Tasks can't proceed

**Solutions:**
```bash
# Wait for lock TTL (default 15s + 5s grace)
# Or restart server to clear all locks

# Check current locks
curl http://localhost:7701/health | jq '.locks'
```

### File Access Issues

#### Path Traversal Error

**Symptoms:**
```
PathTraversalError: Path traversal detected
```

**Solutions:**
- Ensure working directory exists
- Use absolute paths
- Check permissions on target directory

#### Working Directory Not Found

**Symptoms:**
- "Working directory not found" in chat
- Tasks created in wrong location

**Solutions:**
```bash
# Create working directory
mkdir -p ~/devmesh-projects

# Update dashboard to use correct path
```

### Performance Issues

#### High Memory Usage

**Symptoms:**
- System slowing down
- OOM errors

**Solutions:**
```bash
# Check memory usage
ps aux | grep devmesh

# Adjust limits in config
export DEVMESH_GPU_VRAM_GB=8
export DEVMESH_RAM_GB=16

# Restart server
```

#### Slow Dashboard Updates

**Symptoms:**
- Dashboard laggy
- State updates delayed

**Solutions:**
1. Reduce hardware sample interval:
   ```bash
   export DEVMESH_HARDWARE_SAMPLE_INTERVAL_SEC=5
   ```
2. Clear browser cache
3. Check browser console for errors

### Database Issues

#### SQLite Errors

**Symptoms:**
```
sqlite3.OperationalError: database is locked
```

**Solutions:**
```bash
# Reset database (WARNING: loses history)
make reset-db

# Or manually:
rm -rf .devmesh/devmesh.db
```

#### Corrupted Database

**Symptoms:**
- Server crashes on startup
- "database disk image is malformed"

**Solutions:**
```bash
# Backup corrupted db
cp .devmesh/devmesh.db .devmesh/devmesh.db.bak

# Reset
make reset-db
```

## WebSocket Issues

### Connection Dropped

**Symptoms:**
- "Connection closed" in logs
- Agents appear "disconnected"

**Causes:**
1. Network interruption
2. Proxy/firewall timeout
3. Agent process crashed

**Solutions:**
```bash
# Increase heartbeat frequency
export DEVMESH_HEARTBEAT_INTERVAL_SEC=2

# Check agent process
ps aux | grep agent_bridge

# Reconnect agent (it should auto-reconnect if using session_id)
```

### WebSocket Authentication Failed

**Symptoms:**
```
Rate limit exceeded for agent connection
```

**Solutions:**
- Wait before retrying
- Check rate limit configuration
- Restart server if rate limits stuck

## Debugging

### Enable Debug Logging

```bash
export DEVMESH_LOG_LEVEL=DEBUG
python server.py
```

### Check Audit Logs

```bash
# View audit log
tail -f .devmesh/audit.jsonl | jq .
```

### Monitor Metrics

```bash
# Prometheus metrics
curl http://localhost:7701/metrics

# Check with Prometheus (if configured)
# Open http://localhost:9090 in browser
```

### Browser Console

Open browser developer tools (F12) and check:
- Console for JavaScript errors
- Network tab for WebSocket connection
- Application tab for Local Storage

## Error Reference

| Error Code | Meaning | Solution |
|------------|---------|----------|
| `AGENT_NOT_REGISTERED` | Agent tried action before registering | Restart agent |
| `LOCK_CONFLICT` | Another agent holds the lock | Wait or restart conflicting agent |
| `LOCK_TIMEOUT` | Lock acquisition timed out | Retry or adjust timeouts |
| `TASK_NOT_FOUND` | Task ID doesn't exist | Check task ID |
| `TASK_STATE_ERROR` | Invalid state transition | Check task status |
| `DEPENDENCY_ERROR` | Task dependencies not met | Wait for dependencies |
| `INSUFFICIENT_RESOURCES` | Not enough RAM/VRAM | Adjust limits or close apps |
| `TOOL_NOT_FOUND` | AI CLI tool not installed | Install tool or check PATH |
| `TOOL_INVOKE_ERROR` | Tool execution failed | Check tool logs |

## Recovery Procedures

### Full Reset

**WARNING**: This loses all data

```bash
# Stop server (Ctrl+C)

# Reset everything
make clean
make reset-db

# Restart
python server.py
```

### Safe Restart

```bash
# Stop agents first
# (Use dashboard stop button or kill processes)

# Stop server (Ctrl+C)

# Restart server
python server.py

# Reconnect agents
```

### Docker Recovery

```bash
# If using Docker Compose
docker-compose down
docker-compose up -d

# View logs
docker-compose logs -f devmesh-server
```

## Getting Help

1. **Check logs**: `.devmesh/audit.jsonl` and console output
2. **Run diagnostics**: `python check_tools.py`
3. **Check health**: `curl http://localhost:7701/health`
4. **Review configuration**: `cat .env` or environment variables

## Reporting Bugs

When reporting issues, include:

1. DevMesh version (from `server.py` startup log)
2. Python version: `python --version`
3. Operating system
4. Full error message and stack trace
5. Steps to reproduce
6. Relevant audit log entries: `.devmesh/audit.jsonl`
