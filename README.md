# Orchestra

Orchestra is an experimental multi-agent coding system.

Agents can implement well-scoped tasks in massive parallelization. Humans are comparatively better at making high level decisions and directing the work so it matches their intentions. Orchestra leverages parallel agents while keeping the human in the loop, so you have the information to keep making those decisions and design a good system.

## The flow

You describe what you want, and how it should be designed. A designer agent breaks it into tasks and spawns executor agents for each one. The agents run in parallel, and are given tools to communicate with the designer when they are blocked. You come in to polish gaps in the spec, and decide what code to merge.

You can jump into an Executor's execution, see its work, and even stage its changes in your source directory to pair with it.

<demo video>

## Prerequisites

- **git** Orchestra uses git worktrees for parallel development
- **claude-code**
- **tmux**
- **docker:** Orchestra runs agents in isolated containers

## Installation

pip:
```bash
pip install orchestra-code
```

uv:
```bash
uv tool install orchestra-code
```

## Usage

Run `orchestra-setup` on initial install to configure things and make sure you have all the dependencies.

Then go to your coding project, and run `orchestra`, launching the interface.

You're all set! The designer agent is ready in the right pane. Start by describing what you'd like to build or improve, and the designer will help you plan and delegate the work.

Orchestra is a TUI with a 3 pane layout. On the top right, you have the sidebar, with the different agent sessions you can switch between, as well as see the the diff. On the right, you have the actual agent execution, running via claude code, which you can interact with and steer. On the bottom left, you have an extra pane where you can do various things, like open terminals in the various Executor's environments, edit a spec file the agent has access to, etc...

Use `CTRL+S` to shift between the panes.

## Features

- **Executors**: tell the designer to spawn a executor for a task and it will launch an agent, that will then appear in the sidebar, running in an isolated container to accomplish the task. Tell the designer to merge it in when you are happy with the executor's code, for example via the `/merge-child` command you can call in claude.
- **Spec design**: if you type `s` on a session from the sidebar, it will open a spec file in your default editor. This is a place to think and write plans which the designer will collaborate with you on before spawning a executor.
- **Pairing mode**, `p` will take the currently focused agent's session and stage its changes on your local code, so you can directly work together and pair program. Unpair via `p` to restore the original state.

## Full list of sidebar commands

- **`s`**: Open the spec editor (`designer.md`) to plan and discuss tasks with the designer
- **`m`**: Open documentation
- **`p`**: Toggle pairing mode to share your screen with the active session
- **`t`**: Open a terminal in the selected session's work directory
- **`Ctrl+d`**: Delete a selected executor session
- **`Ctrl+q`**: Quit Orchestra

## Configuration

Orchestra stores configuration in two places:

### Global Configuration

`~/.orchestra/config/settings.json` — Global settings for your Orchestra installation.

**Default values:**
```json
{
  "use_docker": true,
  "mcp_port": 8765,
  "ui_theme": "textual-dark"
}
```

**Options:**
- **`use_docker`** (bool): Whether to run executor agents in Docker containers. Set to `false` to run executors on your local machine (not recommended for production).
- **`mcp_port`** (int): Port for the Orchestra MCP server. Change this if 8765 is already in use.
- **`ui_theme`** (string): Textual theme for the Orchestra UI. See [Textual themes](https://textual.textualize.io/guide/themes/) for options.

To modify: Edit `~/.orchestra/config/settings.json` and restart Orchestra.

### Tmux Configuration

`~/.orchestra/config/tmux.conf` — Tmux keybindings and behavior for the Orchestra interface.

Created automatically on first run. Customize this file to change keybindings or tmux behavior. Changes take effect when you restart Orchestra.

**Default keybindings:**
- **`Ctrl+S`**: Switch between panes (top left, bottom left, right)
- **`Ctrl+\\`**: Detach from Orchestra session
- **Mouse wheel**: Scroll through terminal output

## Example workflows


## Troubleshooting


**Spawning Executors doesn't work**:

- check if the orchestra mcp is properly running, via `/mcp` in claude
- make sure you didn't overwrite the config to remove the MCP
- check you aren't occupying the MCP port (by default `8090`)

**Executor is created, won't start automatically:**

- Make sure you ran the setup, and properly authenticated
- Make sure docker is installed.

**Message sending doesn't go through**:

This can be buggy due to differences in user systems sometimes, we're trying to figure out why. Please open an issue with details.


## Contributing
.
If you notice an issue or bug, please [open an issue](https://github.com/fulcrumresearch/orchestra). We also welcome contributions: feel free to open a PR to fix an issue.

You can join the user community to discuss issues and workflows you find useful, on [discord](https://discord.gg/QmMybVuwWp).
