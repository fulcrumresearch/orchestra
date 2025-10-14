"""Async file watcher utility using watchfiles"""

import asyncio
from pathlib import Path
from typing import Callable, Awaitable, Dict, Set, TYPE_CHECKING
from watchfiles import awatch, Change
from .logger import get_logger

if TYPE_CHECKING:
    from .sessions import Session

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
        logger.debug(f"Registered watcher for {file_path}. Total watchers: {len(self._watchers)}")

        # Trigger restart of awatch to pick up new file
        self._stop_event.set()

    def unregister(self, file_path: Path) -> None:
        """
        Unregister a file or specific handler.

        Args:
            file_path: Path to the file
            handler: Specific handler to remove, or None to remove all handlers for this file
        """
        file_path = Path(file_path).resolve()

        if file_path not in self._watchers:
            return

        del self._watchers[file_path]

    async def start(self) -> None:
        """Start the file watching task"""
        if self._task is not None:
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())

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

    async def _run(self) -> None:
        """Main watching loop"""
        logger.debug("File watcher started")
        while not self._should_stop:
            if not self._watchers:
                # No files to watch, sleep briefly
                await asyncio.sleep(0.5)
                continue

            # Get all paths to watch - convert files to their parent directories
            watch_paths = set()
            for path in self._watchers.keys():
                # If it's a file (or doesn't exist yet), watch the parent directory
                if path.is_file() or not path.exists():
                    watch_paths.add(path.parent)
                else:
                    watch_paths.add(path)

            logger.debug(f"Watching {len(self._watchers)} files in {len(watch_paths)} directories")

            # Clear stop event for this iteration
            self._stop_event.clear()

            try:
                # Watch all registered paths (non-recursive)
                async for changes in awatch(*watch_paths, stop_event=self._stop_event, recursive=False):
                    # Group changes by path to avoid calling handlers multiple times
                    # awatch already debounces (1600ms), so changes is a batch
                    changed_paths = {}
                    for change_type, path_str in changes:
                        path = Path(path_str)
                        if path in self._watchers:
                            # Store the last change type for this path
                            changed_paths[path] = change_type

                    # Call handlers once per path
                    for path, change_type in changed_paths.items():
                        handlers = list(self._watchers[path])
                        logger.debug(f"Triggering {len(handlers)} handlers for {path}")
                        for handler in handlers:
                            try:
                                await handler(path, change_type)
                            except Exception as e:
                                logger.error(f"Error in file watcher handler for {path}: {e}")

            except Exception as e:
                logger.error(f"Error in file watcher: {e}")
                await asyncio.sleep(1)

            if self._should_stop:
                break

    def add_designer_watcher(self, designer_md: Path, session: "Session") -> None:
        """
        Register a watcher for designer.md that notifies the session when it changes.

        Args:
            designer_md: Path to the designer.md file
            session: The session to notify
        """
        designer_md = Path(designer_md).resolve()

        async def on_designer_change(path: Path, change_type: Change) -> None:
            """Handler for designer.md changes"""
            logger.debug(f"designer.md changed for session {session.session_id}: {path} ({change_type})")
            try:
                session.send_message("[System] .orchestra/designer.md has been updated. Please review the changes")
                logger.debug(f"Sent message to session {session.session_id}")
            except Exception as e:
                logger.error(f"Failed to send message to session {session.session_id}: {e}")

        self.register(designer_md, on_designer_change)
        logger.debug(f"Registered designer.md watcher for session {session.session_id}: {designer_md}")
