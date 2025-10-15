#!/usr/bin/env python3
"""Interactive setup for Orchestra."""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from orchestra.lib.helpers import ensure_docker_image, ensure_shared_claude_config, get_docker_container_name
from orchestra.lib.sessions import Session
from orchestra.lib.tmux_agent import TmuxProtocol


def main() -> int:
    """Run interactive setup for Orchestra."""
    # Clean up any existing Orchestra processes silently
    try:
        # Kill MCP server if running
        result = subprocess.run(
            ["pgrep", "-f", "orchestra.mcp.server"],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                subprocess.run(["kill", pid], capture_output=True)
    except Exception:
        pass

    try:
        # Kill orchestra tmux server
        subprocess.run(
            ["tmux", "-L", "orchestra", "kill-server"],
            capture_output=True,
            text=True,
        )
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("  Welcome to Orchestra Setup!")
    print("=" * 60)
    print("\nThis setup will guide you through:")
    print("  1. Checking required dependencies")
    print("  2. Configuring Docker for sub-agents (optional)")
    print("  3. Setting up Claude API authentication")
    print()

    # Step 1: Check dependencies
    print("Step 1: Checking dependencies...")
    print("-" * 60)

    missing_deps = []
    required_deps = {
        "tmux": "tmux (install with: apt install tmux / brew install tmux)",
        "claude": "claude CLI (install with: npm install -g @anthropic-ai/claude-code)",
    }

    for cmd, desc in required_deps.items():
        if shutil.which(cmd):
            print(f"  ✓ {cmd} found")
        else:
            print(f"  ✗ {cmd} NOT found")
            missing_deps.append(desc)

    # Check docker separately (optional)
    docker_available = False
    docker_daemon_running = False
    if shutil.which("docker"):
        print(f"  ✓ docker found")
        docker_available = True
        # Check if daemon is running
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"  ✓ docker daemon running")
            docker_daemon_running = True
        else:
            print(f"  ✗ docker daemon NOT running (start docker service)")
            missing_deps.append("docker daemon (not running - start docker service)")
    else:
        print(f"  ✗ docker NOT found (optional, needed for Docker mode)")

    if missing_deps:
        print("\n⚠️  Missing required dependencies:")
        for dep in missing_deps:
            print(f"    - {dep}")
        print("\nPlease install missing dependencies and run setup again.")
        return 1

    print("\n✓ All required dependencies found!")

    # Step 2: Docker setup
    print("\n" + "=" * 60)
    print("Step 2: Docker Configuration")
    print("-" * 60)

    use_docker = False
    if docker_available and docker_daemon_running:
        while True:
            response = input("\nDo you want to use Docker for sub-agents? (y/n): ").strip().lower()
            if response in ['y', 'yes']:
                use_docker = True
                break
            elif response in ['n', 'no']:
                use_docker = False
                break
            else:
                print("Please enter 'y' or 'n'")
    else:
        print("\n⚠️  Docker is not available. Sub-agents will run locally.")
        use_docker = False

    if use_docker:
        print("\n✓ Docker mode selected")
        print("\nChecking for orchestra-image...")

        # Check if image exists
        result = subprocess.run(
            ["docker", "images", "-q", "orchestra-image"],
            capture_output=True,
            text=True,
        )

        if result.stdout.strip():
            print("  ✓ orchestra-image already exists")
        else:
            print("  ⚠️  orchestra-image not found, building now...")
            print("     This may take a few minutes...")
            try:
                ensure_docker_image()
                print("  ✓ orchestra-image built successfully!")
            except Exception as e:
                print(f"\n✗ Failed to build Docker image: {e}")
                return 1

        # Step 3: Shared Claude Configuration (Docker only)
        print("\n" + "=" * 60)
        print("Step 3: Shared Claude Configuration")
        print("-" * 60)

        # Create shared Claude config directory
        shared_claude_dir = Path.home() / ".orchestra" / "shared-claude"
        shared_claude_json = Path.home() / ".orchestra" / "shared-claude.json"

        print("\nCreating shared Claude configuration...")
        print(f"  Location: {shared_claude_dir}")

        # Use default MCP port (will be configured when containers start)
        ensure_shared_claude_config(shared_claude_dir, shared_claude_json, mcp_port=8765)
        print("  ✓ Shared Claude config created")

        # Step 4: Claude API Authentication (Docker only)
        print("\n" + "=" * 60)
        print("Step 4: Claude API Authentication")
        print("-" * 60)

        is_macos = platform.system() == "Darwin"

        if is_macos:
            # macOS: Must authenticate inside container using existing session infrastructure
            print("\n⚠️  You're on macOS - authentication must be done inside a Docker container.")
            print("\nHere's how this works:")
            print("  1. We'll start a temporary Claude session in a container")
            print("  2. You'll be attached to the session automatically")
            print("  3. Complete the authentication flow when Claude prompts you")
            print("  4. Exit Claude when done (Ctrl+D or /exit)")
            print("\nThe authentication will be saved and shared with all sub-agents.")

            while True:
                response = input("\nReady to start authentication session? (y/n): ").strip().lower()
                if response in ['y', 'yes']:
                    break
                elif response in ['n', 'no']:
                    print("\nAuthentication is required for Orchestra to work.")
                    print("Please run setup again when ready.")
                    return 1
                else:
                    print("Please enter 'y' or 'n'")

            print("\nStarting authentication session...")

            # Create a temporary session for authentication
            temp_work_dir = tempfile.mkdtemp(prefix="orchestra-setup-")
            from orchestra.lib.sessions import AgentType

            # Create a temporary session object
            session = Session(
                session_name="setup-auth",
                agent_type=AgentType.EXECUTOR,
                source_path=temp_work_dir,
                work_path=temp_work_dir,
                use_docker=True
            )

            # Create TmuxProtocol in Docker mode
            protocol = TmuxProtocol(default_command="claude", mcp_port=8765, use_docker=True)

            print("  - Starting container...")
            if not protocol.start(session):
                print("\n✗ Failed to start authentication session")
                return 1

            print("  ✓ Session started")
            print("\n" + "=" * 60)
            print("  Launching Interactive Claude Session")
            print("=" * 60)
            print("\nYou'll now be attached to Claude inside the container.")
            print("Complete the authentication when prompted, then exit Claude.")
            print("\nPress Enter to continue...")
            input()

            # Attach to the session interactively (this blocks until user exits)
            container_name = get_docker_container_name(session.session_id)

            attach_result = subprocess.run([
                "docker", "exec", "-it",
                container_name,
                "tmux", "-L", "orchestra", "attach-session", "-t", session.session_id
            ])

            # Clean up the session
            print("\n" + "=" * 60)
            print("Cleaning up...")
            protocol.delete(session)
            shutil.rmtree(temp_work_dir, ignore_errors=True)

            # Verify authentication
            print("Verifying authentication...")
            if shared_claude_json.exists():
                print("  ✓ Configuration file created")
            else:
                print("  ⚠️  Config file not found")
                print("     You may need to re-run: orchestra-setup")

        else:
            # Linux: Check for auth on host
            print("\nChecking authentication...")

            # Check for API key in environment
            if os.environ.get("ANTHROPIC_API_KEY"):
                print("\n✓ ANTHROPIC_API_KEY found in environment")
                print("  This will be passed to Docker containers automatically.")
            else:
                # Check if host has Claude auth
                host_claude_json = Path.home() / ".claude.json"
                if host_claude_json.exists():
                    print("\n✓ Claude authentication found on host")
                    print("  This will be copied to the shared config for containers")
                else:
                    print("\n⚠️  No authentication found")
                    print("\nPlease ensure you're authenticated with Claude CLI on your local system.")
                    print("Your authentication will be automatically shared with Docker containers.")
                    print("\nMake sure you have either:")
                    print("  1. ANTHROPIC_API_KEY environment variable set")
                    print("  2. Claude CLI authenticated (check with: claude)")

                    while True:
                        response = input("\nHave you set up authentication? (y/n): ").strip().lower()
                        if response in ['y', 'yes']:
                            break
                        elif response in ['n', 'no']:
                            print("\nPlease set up authentication and run setup again.")
                            return 1
                        else:
                            print("Please enter 'y' or 'n'")
    else:
        # Local mode
        print("\n✓ Local mode selected")
        print("\nIn local mode, sub-agents will use your host's Claude CLI configuration.")

        # Check for Claude authentication
        print("\n" + "=" * 60)
        print("Step 3: Claude API Authentication")
        print("-" * 60)

        claude_config = Path.home() / ".claude.json"
        if claude_config.exists():
            print(f"\n✓ Claude config found at {claude_config}")
        else:
            print(f"\n⚠️  Claude config not found at {claude_config}")
            print("\nPlease ensure you're authenticated with Claude CLI.")

            while True:
                response = input("\nAre you authenticated with Claude CLI? (y/n): ").strip().lower()
                if response in ['y', 'yes']:
                    if claude_config.exists():
                        print("✓ Authentication successful!")
                        break
                    else:
                        print("⚠️  Config file still not found. Please verify your authentication.")
                elif response in ['n', 'no']:
                    print("\nPlease authenticate with Claude CLI and run setup again.")
                    return 1
                else:
                    print("Please enter 'y' or 'n'")

    # Final summary
    print("\n" + "=" * 60)
    print("  Setup Complete!")
    print("=" * 60)
    print("\nYour Orchestra configuration:")
    print(f"  - Mode: {'Docker' if use_docker else 'Local'}")
    if use_docker:
        print(f"  - Docker image: orchestra-image")
        print(f"  - Shared config: ~/.orchestra/shared-claude/")
    print(f"  - Claude CLI: {shutil.which('claude')}")

    print("\nYou're all set! Run 'orchestra' to start using Orchestra.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
