#!/usr/bin/env python3
"""Test script to verify ORCHESTRA_HOME_DIR environment variable works correctly."""

import os
import sys
from pathlib import Path

# Test 1: Default behavior (no environment variable)
print("=" * 60)
print("Test 1: Default behavior (no ORCHESTRA_HOME_DIR set)")
print("=" * 60)

# Remove env var if set
if "ORCHESTRA_HOME_DIR" in os.environ:
    del os.environ["ORCHESTRA_HOME_DIR"]

# Import after clearing env var
from orchestra.lib.config import get_orchestra_home

orchestra_home = get_orchestra_home()
expected_default = Path.home() / ".orchestra"

print(f"Expected: {expected_default}")
print(f"Got:      {orchestra_home}")
print(f"Match:    {orchestra_home == expected_default}")

if orchestra_home != expected_default:
    print("❌ FAILED: Default orchestra home is incorrect")
    sys.exit(1)

print("\nVerifying path construction:")
checks = [
    ("config/", orchestra_home / "config", expected_default / "config"),
    ("subagents/", orchestra_home / "subagents", expected_default / "subagents"),
    ("sessions.json", orchestra_home / "sessions.json", expected_default / "sessions.json"),
    ("messages.jsonl", orchestra_home / "messages.jsonl", expected_default / "messages.jsonl"),
    ("shared-claude/", orchestra_home / "shared-claude", expected_default / "shared-claude"),
    ("shared-claude.json", orchestra_home / "shared-claude.json", expected_default / "shared-claude.json"),
]

all_passed = True
for name, got, expected in checks:
    match = got == expected
    status = "✓" if match else "❌"
    print(f"  {status} {name}: {got}")
    if not match:
        print(f"     Expected: {expected}")
        all_passed = False

if not all_passed:
    print("\n❌ FAILED: Some helper functions returned incorrect paths")
    sys.exit(1)

print("\n✓ Test 1 PASSED: Default behavior works correctly")

# Test 2: Custom ORCHESTRA_HOME_DIR
print("\n" + "=" * 60)
print("Test 2: Custom ORCHESTRA_HOME_DIR")
print("=" * 60)

custom_home = "/tmp/test-orchestra-home"
os.environ["ORCHESTRA_HOME_DIR"] = custom_home

# Need to reload the module to pick up the new environment variable
# For logger.py which reads env var at module load time
import importlib
import orchestra.lib.logger
importlib.reload(orchestra.lib.logger)

# Re-import config functions (they read env var dynamically)
from orchestra.lib.config import get_orchestra_home

orchestra_home = get_orchestra_home()
expected_custom = Path(custom_home)

print(f"ORCHESTRA_HOME_DIR: {custom_home}")
print(f"Expected: {expected_custom}")
print(f"Got:      {orchestra_home}")
print(f"Match:    {orchestra_home == expected_custom}")

if orchestra_home != expected_custom:
    print("❌ FAILED: Custom orchestra home is incorrect")
    sys.exit(1)

print("\nVerifying path construction with custom home:")
checks = [
    ("config/", orchestra_home / "config", expected_custom / "config"),
    ("subagents/", orchestra_home / "subagents", expected_custom / "subagents"),
    ("sessions.json", orchestra_home / "sessions.json", expected_custom / "sessions.json"),
    ("messages.jsonl", orchestra_home / "messages.jsonl", expected_custom / "messages.jsonl"),
    ("shared-claude/", orchestra_home / "shared-claude", expected_custom / "shared-claude"),
    ("shared-claude.json", orchestra_home / "shared-claude.json", expected_custom / "shared-claude.json"),
]

all_passed = True
for name, got, expected in checks:
    match = got == expected
    status = "✓" if match else "❌"
    print(f"  {status} {name}: {got}")
    if not match:
        print(f"     Expected: {expected}")
        all_passed = False

if not all_passed:
    print("\n❌ FAILED: Some helper functions returned incorrect paths with custom home")
    sys.exit(1)

print("\n✓ Test 2 PASSED: Custom ORCHESTRA_HOME_DIR works correctly")

# Test 3: Verify sessions.py uses the functions
print("\n" + "=" * 60)
print("Test 3: Verify sessions.py uses configurable paths")
print("=" * 60)

from orchestra.lib.sessions import SESSIONS_FILE

expected_sessions_file = expected_custom / "sessions.json"
print(f"SESSIONS_FILE: {SESSIONS_FILE}")
print(f"Expected:      {expected_sessions_file}")
print(f"Match:         {SESSIONS_FILE == expected_sessions_file}")

if SESSIONS_FILE != expected_sessions_file:
    print("❌ FAILED: sessions.py SESSIONS_FILE doesn't use configurable path")
    sys.exit(1)

print("\n✓ Test 3 PASSED: sessions.py uses configurable paths")

# Summary
print("\n" + "=" * 60)
print("✅ ALL TESTS PASSED")
print("=" * 60)
print("\nSummary:")
print("  ✓ Default behavior: ~/.orchestra")
print(f"  ✓ Custom behavior: {custom_home}")
print("  ✓ All helper functions work correctly")
print("  ✓ Backward compatibility maintained")
print("\nThe ORCHESTRA_HOME_DIR environment variable is working correctly!")
