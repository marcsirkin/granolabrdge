"""File system watcher for Granola cache file."""

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable, Optional

from watchdog.events import FileSystemEventHandler, FileModifiedEvent
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class DebouncedHandler(FileSystemEventHandler):
    """File event handler with debouncing."""

    def __init__(
        self,
        target_file: Path,
        callback: Callable[[], None],
        debounce_ms: int = 500,
    ):
        super().__init__()
        self.target_file = target_file.resolve()
        self.callback = callback
        self.debounce_seconds = debounce_ms / 1000.0
        self._last_event_time: float = 0
        self._pending_callback: Optional[asyncio.TimerHandle] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop for scheduling callbacks."""
        self._loop = loop

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Handle file modification events."""
        if event.is_directory:
            return

        # Check if this is our target file
        event_path = Path(event.src_path).resolve()
        if event_path != self.target_file:
            return

        current_time = time.time()
        self._last_event_time = current_time

        # Schedule debounced callback
        if self._loop:
            self._loop.call_soon_threadsafe(self._schedule_callback)

    def _schedule_callback(self) -> None:
        """Schedule the callback after debounce period."""
        # Cancel any pending callback
        if self._pending_callback:
            self._pending_callback.cancel()

        # Schedule new callback
        if self._loop:
            self._pending_callback = self._loop.call_later(
                self.debounce_seconds,
                self._execute_callback,
            )

    def _execute_callback(self) -> None:
        """Execute the callback if enough time has passed."""
        self._pending_callback = None
        logger.debug(f"File change detected: {self.target_file}")
        self.callback()


class GranolaWatcher:
    """Watch Granola cache file for changes."""

    def __init__(
        self,
        cache_path: Path,
        on_change: Callable[[], None],
        debounce_ms: int = 500,
    ):
        """Initialize the watcher.

        Args:
            cache_path: Path to Granola's cache-v3.json
            on_change: Callback to invoke when file changes
            debounce_ms: Debounce period in milliseconds
        """
        self.cache_path = cache_path.expanduser().resolve()
        self.on_change = on_change
        self.debounce_ms = debounce_ms

        self._observer: Optional[Observer] = None
        self._handler: Optional[DebouncedHandler] = None
        self._running = False

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start watching the file.

        Args:
            loop: The asyncio event loop for callbacks
        """
        if self._running:
            return

        if not self.cache_path.parent.exists():
            logger.warning(f"Watch directory does not exist: {self.cache_path.parent}")
            # Create a task to wait for directory
            loop.create_task(self._wait_for_directory(loop))
            return

        self._start_observer(loop)

    def _start_observer(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start the file system observer."""
        self._handler = DebouncedHandler(
            self.cache_path,
            self.on_change,
            self.debounce_ms,
        )
        self._handler.set_loop(loop)

        self._observer = Observer()
        self._observer.schedule(
            self._handler,
            str(self.cache_path.parent),
            recursive=False,
        )
        self._observer.start()
        self._running = True

        logger.info(f"Watching for changes: {self.cache_path}")

    async def _wait_for_directory(self, loop: asyncio.AbstractEventLoop) -> None:
        """Wait for the watch directory to exist."""
        logger.info(f"Waiting for directory: {self.cache_path.parent}")

        while not self.cache_path.parent.exists():
            await asyncio.sleep(5)

        logger.info(f"Directory now exists: {self.cache_path.parent}")
        self._start_observer(loop)

    def stop(self) -> None:
        """Stop watching the file."""
        if self._observer and self._running:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._running = False
            logger.info("File watcher stopped")

    @property
    def is_running(self) -> bool:
        """Check if watcher is running."""
        return self._running
