/**
 * DevMesh Dashboard Enhancements
 * Enhanced UI features for search, filtering, graphs, export, and theme toggle
 */

// Add to the CSS section in dashboard.html
const ENHANCED_STYLES = `
/* SEARCH & FILTER */
.search-bar{
  display:flex;gap:6px;margin-bottom:10px;width:100%;
}
#task-search{
  flex:1;background:var(--bg);border:1px solid var(--bdr2);
  border-radius:5px;color:var(--tx);font-family:var(--fc);font-size:11px;
  padding:6px 9px;outline:none;transition:border-color .15s;
}
#task-search:focus{border-color:var(--gr);box-shadow:0 0 0 2px rgba(58,240,160,.08)}
.filter-badge{
  display:inline-block;background:rgba(58,240,160,.12);border:1px solid rgba(58,240,160,.25);
  border-radius:4px;padding:2px 8px;font-size:10px;color:var(--gr);cursor:pointer;
  transition:all .15s;margin-right:4px;margin-bottom:4px;
}
.filter-badge:hover{background:rgba(58,240,160,.2)}
.filter-badge.active{background:rgba(58,240,160,.25);border-color:rgba(58,240,160,.4)}

/* STATISTICS CARDS */
.stats-row{
  display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;
}
.stat-card{
  background:rgba(58,240,160,.05);border:1px solid rgba(58,240,160,.15);
  border-radius:6px;padding:10px;font-size:10px;
}
.stat-label{color:var(--mu);font-weight:600;margin-bottom:3px}
.stat-value{color:var(--gr);font-size:16px;font-weight:700;font-family:var(--fc)}
.stat-subtext{color:var(--mu);font-size:8px;margin-top:3px}

/* GRAPHS */
.metrics-container{
  background:var(--surf);border:1px solid var(--bdr);border-radius:6px;
  padding:10px;margin-bottom:10px;display:none;
}
.metrics-container.shown{display:block}
.metrics-title{
  font-size:10px;font-weight:700;color:var(--tx);margin-bottom:8px;
  text-transform:uppercase;letter-spacing:.5px;
}
canvas.metric-graph{
  width:100%;height:120px;background:rgba(0,0,0,.1);
  border:1px solid var(--bdr2);border-radius:4px;
}

/* THEME TOGGLE */
html.light-mode{
  --bg:#f5f5f5;--surf:#ffffff;--bdr:#e0e0e0;--bdr2:#d0d0d0;
  --tx:#333333;--mu:#888888;
}
.theme-toggle{
  background:none;border:none;color:var(--mu);cursor:pointer;
  font-size:13px;padding:4px 8px;border-radius:4px;
  transition:background .15s;
}
.theme-toggle:hover{background:rgba(255,255,255,.08)}

/* EXPORT MENU */
.export-menu{
  position:absolute;background:var(--surf);border:1px solid var(--bdr2);
  border-radius:6px;min-width:140px;z-index:50;box-shadow:0 4px 12px rgba(0,0,0,.4);
  display:none;
}
.export-menu.shown{display:block}
.export-item{
  padding:8px 12px;cursor:pointer;font-size:11px;color:var(--tx);
  transition:background .1s;
  border-bottom:1px solid var(--bdr);
}
.export-item:last-child{border:none}
.export-item:hover{background:rgba(58,240,160,.1)}

/* MOBILE RESPONSIVE */
@media (max-width:1024px){
  body{grid-template-columns:1fr}
  #lp{display:none}
  #rp{display:none}
  #cp{grid-column:1/-1}
}
@media (max-width:768px){
  header{flex-direction:column;gap:8px;padding:8px}
  .hstats{gap:10px;font-size:10px}
  #task-list{padding:10px}
  .tr{grid-template-columns:1fr;gap:6px !important}
  .tid{margin-bottom:4px}
  .ts{width:100%;text-align:left}
  .town{text-align:left}
  .chat{padding:10px}
  #ci{font-size:12px}
  #sb{padding:0 12px;font-size:10px}
}
`;

// Enhanced task filtering and statistics
class TaskManager {
  constructor() {
    this.allTasks = {};
    this.filteredTasks = {};
    this.filters = new Set();
    this.searchTerm = '';
    this.stats = {
      total: 0,
      completed: 0,
      working: 0,
      queued: 0,
      failed: 0,
      successRate: 0,
    };
  }

  updateTasks(tasks) {
    this.allTasks = tasks;
    this.applyFilters();
    this.calculateStats();
  }

  setSearchTerm(term) {
    this.searchTerm = term.toLowerCase();
    this.applyFilters();
  }

  toggleFilter(status) {
    if (this.filters.has(status)) {
      this.filters.delete(status);
    } else {
      this.filters.add(status);
    }
    this.applyFilters();
  }

  clearFilters() {
    this.filters.clear();
    this.applyFilters();
  }

  applyFilters() {
    this.filteredTasks = Object.fromEntries(
      Object.entries(this.allTasks).filter(([id, task]) => {
        // Apply search filter
        if (this.searchTerm) {
          const search_text = (
            task.description + ' ' + (task.file || '') + ' ' + (task.owner_model || '')
          ).toLowerCase();
          if (!search_text.includes(this.searchTerm)) return false;
        }

        // Apply status filter
        if (this.filters.size > 0 && !this.filters.has(task.status)) {
          return false;
        }

        return true;
      })
    );
  }

  calculateStats() {
    const tasks = Object.values(this.allTasks);
    this.stats.total = tasks.length;
    this.stats.completed = tasks.filter(t => t.status === 'completed').length;
    this.stats.working = tasks.filter(t => t.status === 'working').length;
    this.stats.queued = tasks.filter(t => t.status === 'queued').length;
    this.stats.failed = tasks.filter(t => t.status === 'failed').length;
    this.stats.successRate = this.stats.total > 0 
      ? Math.round((this.stats.completed / this.stats.total) * 100)
      : 0;
  }

  getStats() {
    return this.stats;
  }

  getFilteredTasks() {
    return this.filteredTasks;
  }
}

// Task execution metrics and graphing
class MetricsCollector {
  constructor(maxDatapoints = 100) {
    this.maxDatapoints = maxDatapoints;
    this.executionRates = []; // Array of {timestamp, count, rate}
    this.successRates = []; // Array of {timestamp, successes, total, rate}
    this.lastUpdate = Date.now();
    this.updateInterval = 60000; // Update metrics every 60 seconds
  }

  recordTaskCompletion(success) {
    const now = Date.now();
    if (now - this.lastUpdate >= this.updateInterval) {
      this.recordMetrics();
      this.lastUpdate = now;
    }
  }

  recordMetrics() {
    const timestamp = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    
    // Would be populated from S.tasks data
    this.executionRates.push({ timestamp, count: 0, rate: 0 });
    if (this.executionRates.length > this.maxDatapoints) {
      this.executionRates.shift();
    }
  }

  drawExecutionGraph(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);

    // Draw grid
    ctx.strokeStyle = 'rgba(255,255,255,.05)';
    ctx.lineWidth = 1;
    for (let i = 0; i < height; i += 20) {
      ctx.beginPath();
      ctx.moveTo(0, i);
      ctx.lineTo(width, i);
      ctx.stroke();
    }

    // Draw execution rate line
    if (this.executionRates.length < 2) return;

    ctx.strokeStyle = 'var(--gr)';
    ctx.lineWidth = 2;
    ctx.beginPath();

    const maxRate = Math.max(...this.executionRates.map(r => r.rate || 0), 1);
    const xStep = width / (this.executionRates.length - 1);

    this.executionRates.forEach((point, idx) => {
      const x = idx * xStep;
      const y = height - (point.rate / maxRate) * height;
      if (idx === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });

    ctx.stroke();
  }

  drawSuccessRateGraph(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);

    // Draw bars for success rate
    if (this.successRates.length === 0) return;

    const barWidth = width / this.successRates.length;
    this.successRates.forEach((point, idx) => {
      const x = idx * barWidth;
      const rateHeight = (point.rate / 100) * height;

      ctx.fillStyle = point.rate > 80 ? 'var(--gr)' : point.rate > 50 ? 'var(--ye)' : 'var(--re)';
      ctx.fillRect(x, height - rateHeight, barWidth - 1, rateHeight);
    });
  }
}

// Export functionality
class ExportManager {
  static exportAsJSON(tasks, filename = 'tasks.json') {
    const json = JSON.stringify(tasks, null, 2);
    this._downloadFile(json, filename, 'application/json');
  }

  static exportAsCSV(tasks, filename = 'tasks.csv') {
    const headers = ['task_id', 'description', 'status', 'owner_model', 'created_at', 'completed_at'];
    const rows = Object.values(tasks).map(t => [
      t.task_id,
      t.description,
      t.status,
      t.owner_model || '',
      t.created_at,
      t.completed_at || '',
    ]);

    let csv = headers.join(',') + '\\n';
    csv += rows.map(row => row.map(cell => `"${cell}"`).join(',')).join('\\n');

    this._downloadFile(csv, filename, 'text/csv');
  }

  static exportAsTSV(tasks, filename = 'tasks.tsv') {
    const headers = ['task_id', 'description', 'status', 'owner_model', 'created_at'];
    const rows = Object.values(tasks).map(t => [
      t.task_id,
      t.description,
      t.status,
      t.owner_model || '',
      t.created_at,
    ]);

    let tsv = headers.join('\\t') + '\\n';
    tsv += rows.map(row => row.join('\\t')).join('\\n');

    this._downloadFile(tsv, filename, 'text/tab-separated-values');
  }

  static _downloadFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
}

// Theme management
class ThemeManager {
  constructor() {
    this.isDarkMode = localStorage.getItem('devmesh_theme') !== 'light';
  }

  toggle() {
    this.isDarkMode = !this.isDarkMode;
    this.apply();
    localStorage.setItem('devmesh_theme', this.isDarkMode ? 'dark' : 'light');
  }

  apply() {
    const html = document.documentElement;
    if (this.isDarkMode) {
      html.classList.remove('light-mode');
    } else {
      html.classList.add('light-mode');
    }
  }

  init() {
    this.apply();
  }

  getIcon() {
    return this.isDarkMode ? '🌙' : '☀️';
  }
}

// Initialize managers on page load
const taskManager = new TaskManager();
const metricsCollector = new MetricsCollector();
const themeManager = new ThemeManager();

// Integrate with existing render functions
function enhanceRenderTasks() {
  const el = document.getElementById('task-list');
  const ts = Object.values(taskManager.getFilteredTasks());

  if (!ts.length) {
    el.innerHTML = '<div class="empty">No tasks matching filters.</div>';
    return;
  }

  el.innerHTML = ts
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    .map(t => `
    <div class="tr">
      <div><div class="tid">${t.task_id}</div><div style="font-size:9px;color:var(--mu)">${t.operation}</div></div>
      <div><div class="tdesc">${t.description}</div><div class="tfile">${t.file || ''}</div>${
        t.depends_on?.length ? `<div style="font-size:9px;color:var(--mu)">deps: ${t.depends_on.join(', ')}</div>` : ''
      }</div>
      <div class="ts ts-${t.status}">${t.status}</div>
      <div class="town">${t.owner_model || '—'}</div>
    </div>`)
    .join('');

  el.scrollTop = el.scrollHeight;
}

function updateTaskSearchAndStats() {
  taskManager.updateTasks(S.tasks);
  const stats = taskManager.getStats();

  // Update stats display
  const statsHTML = `
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-label">Success Rate</div>
        <div class="stat-value">${stats.successRate}%</div>
        <div class="stat-subtext">${stats.completed}/${stats.total} tasks</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">In Progress</div>
        <div class="stat-value">${stats.working}</div>
        <div class="stat-subtext">${stats.queued} queued</div>
      </div>
    </div>
  `;

  // Insert stats before task list if not already present
  if (!document.getElementById('task-stats')) {
    const container = document.getElementById('task-list').parentElement;
    const statsEl = document.createElement('div');
    statsEl.id = 'task-stats';
    statsEl.innerHTML = statsHTML;
    container.insertBefore(statsEl, document.getElementById('task-list'));
  } else {
    document.getElementById('task-stats').innerHTML = statsHTML;
  }

  enhanceRenderTasks();
}

// Export function to add buttons to header
function addEnhancedUIControls() {
  const header = document.querySelector('header .hstats');
  if (!header || document.getElementById('enhanced-controls-added')) return;

  const controlsHTML = `
    <div id="enhanced-controls-added" style="display:flex;gap:10px;margin-left:auto">
      <button class="theme-toggle" onclick="themeManager.toggle();themeManager.init()" title="Toggle theme">
        ${themeManager.getIcon()}
      </button>
      <button onclick="document.getElementById('task-search').focus()" 
              style="background:none;border:none;color:var(--mu);cursor:pointer;font-size:12px">
        🔍
      </button>
      <button id="export-btn" onclick="toggleExportMenu()" 
              style="background:none;border:none;color:var(--mu);cursor:pointer;font-size:12px">
        ⤓
      </button>
    </div>
  `;

  header.insertAdjacentHTML('afterend', controlsHTML);
}

function toggleExportMenu() {
  let menu = document.getElementById('export-menu');
  if (!menu) {
    menu = document.createElement('div');
    menu.id = 'export-menu';
    menu.className = 'export-menu';
    menu.innerHTML = `
      <div class="export-item" onclick="ExportManager.exportAsJSON(S.tasks, 'devmesh-tasks-${Date.now()}.json')">Export JSON</div>
      <div class="export-item" onclick="ExportManager.exportAsCSV(S.tasks, 'devmesh-tasks-${Date.now()}.csv')">Export CSV</div>
      <div class="export-item" onclick="ExportManager.exportAsTSV(S.tasks, 'devmesh-tasks-${Date.now()}.tsv')">Export TSV</div>
    `;
    document.body.appendChild(menu);
  }
  menu.classList.toggle('shown');
}

// Hook into existing render function
const originalRender = window.render;
window.render = function() {
  if (originalRender) originalRender();
  updateTaskSearchAndStats();
  addEnhancedUIControls();
};
`;

module.exports = {
  ENHANCED_STYLES,
  TaskManager,
  MetricsCollector,
  ExportManager,
  ThemeManager,
};
