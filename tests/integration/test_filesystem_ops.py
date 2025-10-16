"""Comprehensive tests for pairing mode functionality and filesystem operations

These tests verify:
1. Pairing mode toggle (activation/deactivation)
2. Git worktree operations
3. Session preparation differences (Designer vs Executor)
4. Filesystem structure correctness
5. Git file manipulation (.git file/directory handling)
"""

import pytest
import subprocess
import shutil
from pathlib import Path
from orchestra.lib.sessions import Session, AgentType, save_session, load_sessions


class TestPairingMode:
    """Tests for pairing mode toggle functionality"""

    def test_pair_creates_symlink_and_updates_git(self, executor_session):
        """Test that pairing creates symlink and updates .git file"""
        source = Path(executor_session.source_path)
        worktree = Path(executor_session.work_path)
        backup = Path(f"{executor_session.source_path}.backup")

        # Initial state checks
        assert source.exists()
        assert worktree.exists()
        assert not backup.exists()
        assert not source.is_symlink()
        assert not executor_session.paired

        # Toggle to paired mode
        success, error = executor_session.toggle_pairing()
        assert success, f"Pairing failed: {error}"
        assert executor_session.paired

        # Verify symlink created
        assert source.is_symlink()
        assert source.resolve() == worktree.resolve()

        # Verify backup created
        assert backup.exists()
        assert backup.is_dir()
        assert (backup / ".git").exists()

        # Verify worktree .git file updated
        worktree_git = worktree / ".git"
        assert worktree_git.exists()
        git_content = worktree_git.read_text()
        assert git_content.startswith("gitdir: ")
        assert "worktrees" in git_content
        assert executor_session.session_id in git_content

    def test_unpair_restores_original_state(self, executor_session):
        """Test that unpairing removes symlink and restores original directory"""
        # Pair the session first
        success, error = executor_session.toggle_pairing()
        assert success, f"Pairing failed: {error}"

        source = Path(executor_session.source_path)
        worktree = Path(executor_session.work_path)
        backup = Path(f"{executor_session.source_path}.backup")

        # Initial state checks (should be paired)
        assert source.is_symlink()
        assert backup.exists()
        assert executor_session.paired

        # Toggle to unpaired mode
        success, error = executor_session.toggle_pairing()
        assert success, f"Unpairing failed: {error}"
        assert not executor_session.paired

        # Verify symlink removed
        assert not source.is_symlink()
        assert source.is_dir()

        # Verify backup removed (restored to source)
        assert not backup.exists()

        # Verify original directory restored
        assert source.exists()
        assert (source / ".git").exists()

        # Verify worktree .git file updated back to original location
        worktree_git = worktree / ".git"
        git_content = worktree_git.read_text()
        assert git_content.startswith("gitdir: ")
        assert "worktrees" in git_content


class TestSessionPreparation:
    """Tests for session preparation differences between agent types"""

    def test_designer_uses_source_path(self, temp_git_repo):
        """Test that designer session works directly in source directory"""
        from orchestra.lib.sessions import Session, AgentType

        session = Session(
            session_name="designer",
            agent_type=AgentType.DESIGNER,
            source_path=str(temp_git_repo),
            use_docker=False,
        )
        session.prepare()

        # Designer work_path should be same as source_path
        assert session.work_path == session.source_path
        assert Path(session.work_path) == temp_git_repo


class TestFilesystemStructure:
    """Tests for correct filesystem layout verification"""

    def test_designer_directory_structure(self, designer_session):
        """Test that designer session has correct file structure"""
        work_path = Path(designer_session.work_path)

        # Should be working in source directory
        assert work_path == Path(designer_session.source_path)

        # Should have .claude directory
        claude_dir = work_path / ".claude"
        assert claude_dir.exists()

        # Should have orchestra.md
        orchestra_md = claude_dir / "orchestra.md"
        assert orchestra_md.exists()
        content = orchestra_md.read_text()
        assert "designer" in content.lower() or "Designer" in content

        # Should have CLAUDE.md with import
        claude_md = claude_dir / "CLAUDE.md"
        assert claude_md.exists()
        assert "@orchestra.md" in claude_md.read_text()

        # Designer should NOT have merge-child command
        merge_cmd = claude_dir / "commands" / "merge-child.md"
        assert not merge_cmd.exists()

    def test_executor_directory_structure(self, executor_session):
        """Test that executor session has correct file structure"""
        work_path = Path(executor_session.work_path)

        # Should be in separate worktree
        assert ".orchestra/worktrees" in str(work_path)
        assert work_path != Path(executor_session.source_path)

        # Should have .claude directory
        claude_dir = work_path / ".claude"
        assert claude_dir.exists()

        # Should have orchestra.md with executor instructions
        orchestra_md = claude_dir / "orchestra.md"
        assert orchestra_md.exists()
        content = orchestra_md.read_text()
        assert "executor" in content.lower() or "Executor" in content

        # Should have CLAUDE.md with import
        claude_md = claude_dir / "CLAUDE.md"
        assert claude_md.exists()
        assert "@orchestra.md" in claude_md.read_text()

        # Executor SHOULD have merge-child command
        merge_cmd = claude_dir / "commands" / "merge-child.md"
        assert merge_cmd.exists()

        # Should have .git file (not directory)
        git_file = work_path / ".git"
        assert git_file.exists()
        assert git_file.is_file()
        content = git_file.read_text()
        assert content.startswith("gitdir: ")

    def test_executor_has_instructions_file(self, temp_git_repo, designer_session):
        """Test that spawned executor has instructions.md file"""
        from unittest.mock import patch

        with patch("orchestra.lib.tmux_agent.TmuxProtocol.start", return_value=True):
            child = designer_session.spawn_executor(
                session_name="child-with-instructions",
                instructions="Build authentication system",
            )

        instructions_file = Path(child.work_path) / "instructions.md"
        assert instructions_file.exists()
        content = instructions_file.read_text()
        assert "Build authentication system" in content
