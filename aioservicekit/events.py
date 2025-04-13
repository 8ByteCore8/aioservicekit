import asyncio
import inspect
import signal
from collections.abc import Coroutine
from typing import (
    Any,
    Callable,
    Generic,
    Optional,
    ParamSpec,
    Self,
    cast,
)

_P = ParamSpec("_P")

__all__ = [
    "EventError",
    "EventClosedError",
    "Event",
    "on_shutdown",
]


class EventError(Exception):
    """Base exception for event-related errors."""

    pass


class EventClosedError(EventError):
    """Raised when an operation is attempted on a closed event."""

    pass


class Event(Generic[_P]):
    """
    Event class that allows registering listeners and emitting events.

    Supports both synchronous and asynchronous listeners. Can be used as a context manager
    to ensure the event is closed upon exiting the context.

    Type Args:
        _P: The ParamSpec defining the argument types that listeners registered
            to this event will accept.
    """

    __closed__: bool = False
    __listeners__: set[Callable[_P, None | Coroutine[Any, Any, None]]]

    def __init__(self) -> None:
        """
        Initialize a new Event instance.
        """
        self.__listeners__ = set()

    def __enter__(self) -> Self:
        """
        Enter the runtime context related to this object.

        Returns:
            The event instance itself.
        """
        return self

    def __exit__(self, *args) -> None:
        """
        Exit the runtime context and close the event.
        """
        self.close()

    async def __emit__(self, *args: _P.args, **kwargs: _P.kwargs) -> None:
        """Internal method to execute listeners."""
        async with asyncio.TaskGroup() as group:
            for listener in self.__listeners__:
                try:
                    res = listener(*args, **kwargs)
                    if inspect.isawaitable(res):
                        group.create_task(res)
                except Exception:
                    # Consider logging the exception instead of passing silently
                    pass

    @property
    def is_closed(self) -> bool:
        """Check if the event is closed."""
        return self.__closed__

    def add_listener(
        self, listener: Callable[_P, None | Coroutine[Any, Any, None]]
    ) -> None:
        """
        Subscribe a listener callable to this event.

        The listener can be a regular function or an async function (coroutine).
        It will be called with the arguments provided during the `emit` call.

        Args:
            listener: The callable function or coroutine to be added as a listener.

        Raises:
            EventClosedError: If the event has already been closed.
        """
        if self.__closed__:
            raise EventClosedError()

        if callable(listener):
            self.__listeners__.add(listener)

    def remove_listener(
        self, listener: Callable[_P, None | Coroutine[Any, Any, None]]
    ) -> None:
        """
        Unsubscribe a listener callable from this event.

        Args:
            listener: The listener callable to remove.

        Raises:
            EventClosedError: If the event has already been closed.
        """
        if self.__closed__:
            raise EventClosedError()

        if listener in self.__listeners__:
            self.__listeners__.discard(listener)

    async def emit(self, *args: _P.args, **kwargs: _P.kwargs) -> None:
        """
        Emit the event, calling all registered listeners with the provided arguments.

        Synchronous listeners are called directly. Asynchronous listeners are scheduled
        to run concurrently within an `asyncio.TaskGroup`. Listener exceptions are
        caught and ignored (consider using logging for better diagnostics).

        Args:
            *args: Positional arguments to pass to each listener.
            **kwargs: Keyword arguments to pass to each listener.

        Raises:
            EventClosedError: If the event has already been closed.
        """
        if self.__closed__:
            raise EventClosedError()

        # Wrap the internal __emit__ in a task to ensure it runs asynchronously
        # even if called from a context where the caller might not await it immediately.
        await asyncio.create_task(self.__emit__(*args, **kwargs))

    def close(self) -> None:
        """
        Close the event, preventing further listener additions or emissions.

        This clears all registered listeners. Attempting further operations
        on a closed event will raise an `EventClosedError`. This operation
        is idempotent; calling close on an already closed event does nothing.
        """
        if self.__closed__:
            return

        self.__closed__ = True
        self.__listeners__.clear()


__ON_SHUTDOWN__: Optional[Event[signal.Signals]] = None


def on_shutdown() -> Event[signal.Signals]:
    """
    Get the global shutdown event instance, creating and configuring it if necessary.

    This function ensures a singleton `Event` instance is created and configured
    to listen for typical shutdown signals (SIGHUP, SIGTERM, SIGINT). When a
    handled signal is received, the event is emitted with the signal number
    as an argument, and then the event is closed.

    It attempts to use `asyncio`'s loop signal handling if a loop is running,
    otherwise falls back to the standard `signal.signal` mechanism.

    Returns:
        The singleton event instance that triggers on shutdown signals.

    Raises:
        RuntimeError: If the shutdown event fails to initialize (this should
                      theoretically not happen under normal circumstances).
    """
    global __ON_SHUTDOWN__

    if __ON_SHUTDOWN__ is None:
        __ON_SHUTDOWN__ = Event[signal.Signals]()

        # This inner function is the actual callback passed to the signal handler setup.
        # It captures the specific signal it's handling.
        def handle_signal(signal_received: signal.Signals) -> Callable[..., None]:
            """Factory to create a signal handler closure for a specific signal."""

            def inner(*args, **kwargs) -> None:
                """The actual signal handler function called by the system."""
                # Ensure the event emitter is correctly typed for the cast
                shutdown_event = cast(Event[signal.Signals], __ON_SHUTDOWN__)
                try:
                    # Try to get the running asyncio loop and schedule the emit task.
                    loop = asyncio.get_running_loop()
                    # Schedule emit to run in the loop, but don't block the signal handler
                    loop.create_task(shutdown_event.emit(signal_received))
                except RuntimeError:
                    # If no loop is running, run the emit coroutine directly using asyncio.run.
                    # This might happen if the signal is received before the loop starts
                    # or after it stops. This blocks until emit completes.
                    asyncio.run(shutdown_event.emit(signal_received))
                finally:
                    # Ensure the event is closed after emission attempt, regardless of loop state.
                    # This prevents further emissions or listener modifications.
                    if not shutdown_event.is_closed:
                        shutdown_event.close()

            return inner

        # Signals to handle for shutdown
        signals_to_handle = [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]

        try:
            # Attempt to use asyncio's signal handling mechanism if a loop is available
            loop = asyncio.get_running_loop()
            for s in signals_to_handle:
                # Create a unique handler for each signal using the factory
                loop.add_signal_handler(s, handle_signal(s))
        except RuntimeError:
            # Fallback to standard signal handling if no asyncio loop is running
            for s in signals_to_handle:
                # Create a unique handler that fits the signal.signal signature
                signal.signal(s, handle_signal(s))

    # Ensure __ON_SHUTDOWN__ is not None before returning
    if __ON_SHUTDOWN__ is None:
        # This path should theoretically not be reached due to the logic above,
        # but acts as a safeguard.
        raise RuntimeError(
            "Failed to initialize the shutdown event."
        )  # Or handle appropriately

    return __ON_SHUTDOWN__
