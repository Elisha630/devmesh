#!/usr/bin/env python3
"""
Verification script for DevMesh fixes integration.

Run this to verify all required files exist and dependencies are ready.
"""

import os
import sys
import subprocess
from pathlib import Path


def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print("=" * 60)


def print_ok(text):
    print(f"  ✅ {text}")


def print_warn(text):
    print(f"  ⚠️  {text}")


def print_error(text):
    print(f"  ❌ {text}")


def check_python_version():
    """Check Python version (3.10+ required)."""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 10:
        print_ok(f"Python {version.major}.{version.minor} ✓")
        return True
    else:
        print_error(f"Python {version.major}.{version.minor} (need 3.10+)")
        return False


def check_files_exist():
    """Check all created files exist."""
    base_dir = Path(__file__).parent
    required_files = [
        "error_handler.py",
        "config_manager.py",
        "dashboard_enhancements.js",
        "services/result_cache.py",
        "services/webhook_manager.py",
        "services/task_templates.py",
        "services/file_watcher.py",
        "services/ws_health.py",
        "INTEGRATION_GUIDE.md",
        "IMPLEMENTATION_SUMMARY.md",
        "QUICK_START.md",
    ]

    all_exist = True
    for file_name in required_files:
        file_path = base_dir / file_name
        if file_path.exists():
            size = file_path.stat().st_size
            print_ok(f"{file_name:40} ({size:,} bytes)")
        else:
            print_error(f"{file_name:40} MISSING")
            all_exist = False

    return all_exist


def check_dependencies():
    """Check if Python dependencies are installed."""
    required = {
        "pydantic": "pydantic>=2.0.0",
        "yaml": "pyyaml>=6.0",
        "httpx": "httpx>=0.24.0",
        "watchfiles": "watchfiles>=0.20.0",
        "tomli": "tomli>=2.0.1",
    }

    missing = []
    installed = []

    for import_name, package_name in required.items():
        try:
            __import__(import_name)
            installed.append(package_name)
        except ImportError:
            missing.append(package_name)

    for pkg in installed:
        print_ok(f"{pkg:40} installed")

    if missing:
        print()
        for pkg in missing:
            print_warn(f"{pkg:40} NOT installed")
        print()
        print("  Install missing dependencies with:")
        print(f"    pip install {' '.join(missing)}")
        return False

    return True


def check_file_contents():
    """Quick sanity check on file contents."""
    base_dir = Path(__file__).parent

    checks = [
        ("error_handler.py", "StructuredErrorHandler"),
        ("config_manager.py", "ConfigManager"),
        ("dashboard_enhancements.js", "class TaskManager"),
        ("services/result_cache.py", "class ResultCache"),
        ("services/webhook_manager.py", "class WebhookManager"),
        ("services/task_templates.py", "class TemplateManager"),
        ("services/file_watcher.py", "class FileWatcher"),
        ("services/ws_health.py", "class HealthMonitor"),
    ]

    all_valid = True
    for file_name, search_text in checks:
        file_path = base_dir / file_name
        if not file_path.exists():
            print_error(f"{file_name:40} file not found")
            all_valid = False
            continue

        try:
            content = file_path.read_text()
            if search_text in content:
                print_ok(f"{file_name:40}")
            else:
                print_warn(f"{file_name:40} - '{search_text}' not found")
        except Exception as e:
            print_error(f"{file_name:40} - {str(e)}")
            all_valid = False

    return all_valid


def check_project_structure():
    """Check that project structure is intact."""
    base_dir = Path(__file__).parent

    dirs = [
        "services",
        "handlers",
        "tests",
        "docs",
    ]

    all_exist = True
    for dir_name in dirs:
        dir_path = base_dir / dir_name
        if dir_path.is_dir():
            print_ok(f"{dir_name:40} ✓")
        else:
            print_error(f"{dir_name:40} NOT FOUND")
            all_exist = False

    return all_exist


def print_integration_guide():
    """Print quick integration guide."""
    print_header("Integration Guide (see QUICK_START.md for details)")

    steps = [
        "1. Install dependencies: pip install -r requirements.txt",
        "2. Add error_handler to server.py __init__()",
        "3. Replace exception handlers with specific types",
        "4. Add config_manager initialization",
        "5. Initialize all services in server.__init__()",
        "6. Hook WebSocket health monitoring in handlers",
        "7. Add dashboard UI enhancements to dashboard.html",
        "8. Test all features",
    ]

    for step in steps:
        print(f"  {step}")


def main():
    """Run all checks."""
    print_header("DevMesh Fixes Verification")

    all_checks_pass = True

    print_header("1. Python Version")
    if not check_python_version():
        all_checks_pass = False

    print_header("2. Project Structure")
    if not check_project_structure():
        all_checks_pass = False

    print_header("3. Created Files")
    if not check_files_exist():
        all_checks_pass = False

    print_header("4. File Contents (Quick Check)")
    if not check_file_contents():
        all_checks_pass = False

    print_header("5. Python Dependencies")
    if not check_dependencies():
        all_checks_pass = False

    print()
    if all_checks_pass:
        print_header("✅ All Checks Passed!")
        print_integration_guide()
        print()
        print("  Status: Ready for integration")
        print()
        return 0
    else:
        print_header("❌ Some Checks Failed")
        print()
        print("  Please fix the issues above and run again.")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
