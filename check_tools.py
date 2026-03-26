#!/usr/bin/env python3
"""Quick diagnostic to check if CLI tools are available."""

import subprocess
import sys

from config import KNOWN_CLI_TOOLS

print("Checking CLI tool availability:\n")
for tool_info in KNOWN_CLI_TOOLS:
    tool = tool_info["name"]
    cmd = tool_info["cmd"]
    try:
        result = subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            timeout=2,
            text=True
        )
        if result.returncode == 0:
            version = result.stdout.strip().split('\n')[0]
            print(f"✓ {tool:10} ({cmd}) — {version}")
        else:
            print(f"✗ {tool:10} ({cmd}) — not available")
    except FileNotFoundError:
        print(f"✗ {tool:10} ({cmd}) — not installed")
    except subprocess.TimeoutExpired:
        print(f"? {tool:10} ({cmd}) — timeout (may be slow)")
    except Exception as e:
        print(f"✗ {tool:10} ({cmd}) — error: {e}")

print("\n" + "="*60)
print("If tools show as ✗, you need to install them first.")
print("==="*20)
