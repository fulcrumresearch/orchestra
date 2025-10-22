"""Async file watcher utility using watchfiles"""

import asyncio
import time
from pathlib import Path
from typing import Callable, Awaitable, Dict, Set, TYPE_CHECKING
from watchfiles import awatch
from .logger import get_logger

if TYPE_CHECKING:
    from .sessions import Session

logger = get_logger(__name__)

FileChangeHandler = Callable[[Path, float], Awaitable[None]]
FileChangeFilter = Callable[[Path, float], bool]


class FileWatcher:
    """
    Centralized async file watcher using watchfiles.

    Allows registering multiple files with their handlers.
    Runs a single background task to watch all registered files.
    """

    def __init__(self):
        self._watchers: Dict[Path, Set[FileChangeHandler]] = {}
        self._last_call_times: Dict[tuple, float] = {}  # Key: (path, handler), Value: timestamp
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
                # TODO: fix this unclean logic
                await asyncio.sleep(0.5)
                continue
            # Get all paths to watch - convert files to their parent directories to handle awatch buggy file logic when editors use tmpfiles
            watch_paths = set()
            for path in self._watchers.keys():
                if path.is_file() or not path.exists():
                    watch_paths.add(path.parent)
                else:
                    watch_paths.add(path)

            if not watch_paths:
                # No files to watch yet, wait for registration
                await asyncio.sleep(0.5)
                continue

            logger.debug(f"Watching {len(self._watchers)} files in {len(watch_paths)} directories")

            # Clear stop event for this iteration
            self._stop_event.clear()

            async for changes in awatch(*watch_paths, stop_event=self._stop_event, recursive=False):
                # Group changes by path to avoid calling handlers multiple times
                # awatch already debounces (1600ms), so changes is a batch
                changed_paths = set()
                for _, path_str in changes:
                    path = Path(path_str).resolve()
                    changed_paths.add(path)

                # Call handlers once per path
                for path in changed_paths:
                    if path not in self._watchers:
                        continue

                    handlers = list(self._watchers[path])
                    logger.debug(f"Triggering {len(handlers)} handlers for {path}")
                    for handler in handlers:
                        # Get last call time for this handler
                        handler_key = (path, handler.__name__)
                        last_call_time = self._last_call_times.get(handler_key, 0.0)
                        self._last_call_times[handler_key] = time.time()

                        await handler(path, last_call_time)

            if self._should_stop:
                break

    def add_session_change_notifier(self, path: Path, session: "Session", filter_fn: FileChangeFilter | None = None) -> None:
        """
        Register a watcher for designer.md that notifies the session when it changes.

        Args:
            designer_md: Path to the designer.md file
            session: The session to notify
        """

        path = path.resolve()

        async def on_file_change(path: Path, last_call_time: float) -> None:
            """Handler for designer.md changes"""

            current_time = time.time()
            if current_time - last_call_time >= 5 and (not filter_fn or filter_fn(path)):
                session.send_message(f"[System] {path} has been updated. Please review the changes")

        self.register(path, on_file_change)
