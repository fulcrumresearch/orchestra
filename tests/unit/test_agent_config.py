import pytest
from pathlib import Path
import tempfile
import yaml

from orchestra.lib.agent import load_agent, Agent, DESIGNER_AGENT


def test_load_builtin_agent_no_config():
    """Test loading built-in agent when no config exists"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / ".orchestra" / "config"
        config_dir.mkdir(parents=True)

        agent = load_agent("designer", config_dir)
        assert agent.name == "designer"
        assert agent == DESIGNER_AGENT


def test_override_builtin_prompt():
    """Test overriding built-in agent prompt"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / ".orchestra" / "config"
        config_dir.mkdir(parents=True)

        # Create custom prompt
        prompt_file = config_dir / "custom_designer.md"
        prompt_file.write_text("Custom designer prompt")

        # Create agents.yaml
        agents_yaml = config_dir / "agents.yaml"
        agents_yaml.write_text(yaml.dump({
            "agents": {
                "designer": {
                    "prompt_file": "custom_designer.md"
                }
            }
        }))

        agent = load_agent("designer", config_dir)
        assert agent.name == "designer"
        assert agent.prompt == "Custom designer prompt"


def test_simple_config_agent():
    """Test creating simple config-based agent"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / ".orchestra" / "config"
        config_dir.mkdir(parents=True)

        # Create agents.yaml
        agents_yaml = config_dir / "agents.yaml"
        agents_yaml.write_text(yaml.dump({
            "agents": {
                "code-reviewer": {
                    "prompt": "You are a code reviewer",
                    "use_docker": False
                }
            }
        }))

        agent = load_agent("code-reviewer", config_dir)
        assert agent.name == "code-reviewer"
        assert agent.prompt == "You are a code reviewer"
        assert agent.use_docker == False
        # Should have executor setup behavior
        assert hasattr(agent, 'setup')


def test_unknown_agent_raises():
    """Test that unknown agent raises ValueError"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / ".orchestra" / "config"
        config_dir.mkdir(parents=True)

        with pytest.raises(ValueError, match="Unknown agent"):
            load_agent("nonexistent", config_dir)
