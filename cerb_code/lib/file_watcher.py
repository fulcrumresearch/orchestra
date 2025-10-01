"""Async file watcher utility using watchfiles"""
import asyncio
from pathlib import Path
from typing import Callable, Awaitable, Dict, Set, TYPE_CHECKING
from watchfiles import awatch, Change
from .logger import get_logger

if TYPE_CHECKING:
    from .tmux_agent import TmuxProtocol

logger = get_logger(__name__)

# Type for async handler functions
FileChangeHandler = Callable[[Path, Change], Awaitable[None]]


class FileWatcher:
    """
    Centralized async file watcher using watchfiles.

    Allows registering multiple files with their handlers.
    Runs a single background task to watch all registered files.
    """

    def __init__(self):
        self._watchers: Dict[Path, Set[FileChangeHandler]] = {}
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._should_stop = False  # Flag to distinguish stop vs restart

    def register(self, file_path: Path, handler: FileChangeHandler) -> None:
        """
        Register a file to watch with a handler callback.

        Args:
            file_path: Path to the file to watch
            handler: Async callback function(path, change_type) to call on changes
        """
        file_path = Path(file_path).resolve()

        if file_path not in self._watchers:
            self._watchers[file_path] = set()

        self._watchers[file_path].add(handler)
        logger.info(f"Registered watcher for {file_path}")

        # Trigger restart to pick up new file
        self._stop_event.set()

    def unregister(self, file_path: Path, handler: FileChangeHandler | None = None) -> None:
        """
        Unregister a file or specific handler.

        Args:
            file_path: Path to the file
            handler: Specific handler to remove, or None to remove all handlers for this file
        """
        file_path = Path(file_path).resolve()

        if file_path not in self._watchers:
            return

        if handler is None:
            # Remove all handlers for this file
            del self._watchers[file_path]
            logger.info(f"Unregistered all watchers for {file_path}")
        else:
            # Remove specific handler
            self._watchers[file_path].discard(handler)
            if not self._watchers[file_path]:
                del self._watchers[file_path]
            logger.info(f"Unregistered handler for {file_path}")

    async def start(self) -> None:
        """Start the file watching task"""
        if self._task is not None:
            logger.warning("FileWatcher already started")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())
        logger.info("FileWatcher started")

    async def stop(self) -> None:
        """Stop the file watching task"""
        if self._task is None:
            return

        self._should_stop = True
        self._stop_event.set()

        try:
            await asyncio.wait_for(self._task, timeout=2.0)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None
        logger.info("FileWatcher stopped")

    async def _run(self) -> None:
        """Main watching loop"""
        while not self._should_stop:
            if not self._watchers:
                # No files to watch, sleep briefly
                await asyncio.sleep(0.5)
                continue

            # Get all paths to watch
            watch_paths = list(self._watchers.keys())

            # Clear stop event for this iteration
            self._stop_event.clear()

            try:
                # Watch all registered files (non-recursive)
                async for changes in awatch(*watch_paths, stop_event=self._stop_event, recursive=False):
                    for change_type, path_str in changes:
                        path = Path(path_str)

                        # Find handlers for this file
                        if path in self._watchers:
                            handlers = list(self._watchers[path])

                            # Call all handlers for this file
                            for handler in handlers:
                                try:
                                    await handler(path, change_type)
                                except Exception as e:
                                    logger.error(f"Error in file watcher handler for {path}: {e}")

            except Exception as e:
                logger.error(f"Error in file watcher: {e}")
                await asyncio.sleep(1)  # Brief pause before retrying

            # awatch exited - check if we're restarting or stopping
            if self._should_stop:
                break

            # Otherwise, loop continues and restarts awatch with updated file list
            logger.info(f"Restarting file watcher with {len(self._watchers)} files")


def watch_designer_file(
    file_watcher: FileWatcher,
    protocol: "TmuxProtocol",
    designer_md: Path,
    session_id: str
) -> None:
    """
    Register a watcher for designer.md that notifies the session when it changes.

    Watches the parent directory to handle vim's atomic saves (delete + rename).

    Args:
        file_watcher: The FileWatcher instance to register with
        protocol: The TmuxProtocol instance to send messages with
        designer_md: Path to the designer.md file
        session_id: ID of the session to notify
    """
    designer_md = Path(designer_md).resolve()
    designer_filename = designer_md.name
    work_dir = designer_md.parent

    async def on_dir_change(path: Path, change_type: Change) -> None:
        """Handler for directory changes - filter for designer.md"""
        # Only process changes to designer.md
        if path.name != designer_filename:
            return

        logger.info(f"designer.md changed ({change_type.name}) for session {session_id}")

        # Skip delete events - vim does atomic saves (delete old, rename temp)
        # We'll catch the added/modified event from the rename
        if change_type == Change.deleted:
            logger.debug(f"Skipping notification for delete event (atomic save)")
            return

        # Send notification to the session
        success = protocol.send_message(
            session_id,
            "designer.md has been updated. Please review the changes."
        )

        if success:
            logger.info(f"Notified session {session_id} about designer.md update")
        else:
            logger.error(f"Failed to notify session {session_id}")

    # Watch the parent directory (non-recursively) to handle atomic saves
    file_watcher.register(work_dir, on_dir_change)
    logger.info(f"Registered designer.md watcher for session {session_id}: {designer_md}")
