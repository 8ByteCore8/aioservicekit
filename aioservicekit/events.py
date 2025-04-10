import asyncio
import inspect
import signal
from collections.abc import Coroutine
from typing import (
    Any,
    Callable,
    Generic,
    Optional,
    Self,
    TypeVarTuple,
    cast,
)

__all__ = [
    "EventError",
    "EventClosedError",
    "Event",
    "on_shutdown",
]

_ARGS = TypeVarTuple("_ARGS")


class EventError(Exception):
    """Base exception for event-related errors."""

    pass


class EventClosedError(EventError):
    """Raised when an operation is attempted on a closed event."""

    pass


class Event(Generic[*_ARGS]):
    """
    Event class that allows registering listeners and emitting events.

    Supports both synchronous and asynchronous listeners. Can be used as a context manager
    to ensure the event is closed upon exiting the context.

    Type Args:
        *_ARGS: The argument types that listeners registered to this event will accept.
    """

    __closed__: bool = False
    __listeners__: set[Callable[[*_ARGS], None | Coroutine[Any, Any, None]]]

    def __enter__(self) -> Self:
        """
        Enter the runtime context related to this object.

        Returns:
            Self: The event instance itself.
        """
        return self

    def __exit__(self, *args) -> None:
        """
        Exit the runtime context and close the event.
        """
        self.close()

    def __init__(self) -> None:
        """
        Initialize a new Event instance.
        """
        self.__listeners__ = set()

    def add_listener(
        self, listener: Callable[[*_ARGS], None | Coroutine[Any, Any, None]]
    ) -> None:
        """
        Subscribe a listener callable to this event.

        The listener can be a regular function or an async function (coroutine).
        It will be called with the arguments provided during the `emit` call.

        Args:
            listener (Callable[[*_ARGS], None | Coroutine[Any, Any, None]]):
                The callable function or coroutine to be added as a listener.

        Raises:
            EventClosedError: If the event has already been closed.
        """
        if self.__closed__:
            raise EventClosedError()

        if listener not in self.__listeners__ and callable(listener):
            self.__listeners__.add(listener)

    def remove_listener(
        self, listener: Callable[[*_ARGS], None | Coroutine[Any, Any, None]]
    ) -> None:
        """
        Unsubscribe a listener callable from this event.

        Args:
            listener (Callable[[*_ARGS], None | Coroutine[Any, Any, None]]):
                The listener callable to remove.

        Raises:
            EventClosedError: If the event has already been closed.
        """
        if self.__closed__:
            raise EventClosedError()

        if listener in self.__listeners__:
            self.__listeners__.remove(listener)

    async def __emit__(self, *args: *_ARGS):
        """Internal method to execute listeners."""
        async with asyncio.TaskGroup() as group:
            for listener in self.__listeners__:
                try:
                    res = listener(*args)
                    if inspect.isawaitable(res):
                        group.create_task(res)
                except Exception:
                    pass

    async def emit(self, *args: *_ARGS) -> None:
        """
        Emit the event, calling all registered listeners with the provided arguments.

        Synchronous listeners are called directly. Asynchronous listeners are scheduled
        to run concurrently within an `asyncio.TaskGroup`. Listener exceptions are
        caught and printed (consider using logging).

        Args:
            *args (*_ARGS): The arguments to pass to each listener.

        Raises:
            EventClosedError: If the event has already been closed.

        Returns:
            Coroutine[Any, Any, None]: A coroutine that completes when all listeners
                                       have been processed.
        """
        if self.__closed__:
            raise EventClosedError()

        # Wrap the internal __emit__ in a task to ensure it runs asynchronously
        # even if called from a context where the caller might not await it immediately.
        await asyncio.create_task(self.__emit__(*args))

    def close(self) -> None:
        """
        Close the event, preventing further listener additions or emissions.

        This clears all registered listeners. Attempting further operations
        on a closed event will raise an `EventClosedError`.

        Raises:
            EventClosedError: If the event has already been closed.
        """
        if self.__closed__:
            raise EventClosedError()

        self.__closed__ = True
        self.__listeners__.clear()


__ON_SHUTDOWN__: Optional[Event[signal.Signals]] = None


def on_shutdown() -> Event[signal.Signals]:
    """
    Get the global shutdown event instance, creating and configuring it if necessary.

    Returns:
        Event[signal.Signals]: The singleton event instance that triggers on shutdown signals.
    """
    global __ON_SHUTDOWN__

    if __ON_SHUTDOWN__ is None:
        __ON_SHUTDOWN__ = Event[signal.Signals]()

        # This inner function is the actual callback passed to the signal handler setup.
        # It captures the specific signal it's handling.
        def handle_signal(signal_received: signal.Signals) -> Callable[[], None]:
            """Factory to create a signal handler closure."""

            def inner() -> None:
                """The actual signal handler function."""
                # Ensure the event emitter is correctly typed for the cast
                shutdown_event = cast(Event[signal.Signals], __ON_SHUTDOWN__)
                try:
                    # Try to get the running asyncio loop and schedule the emit task.
                    loop = asyncio.get_running_loop()
                    loop.create_task(shutdown_event.emit(signal_received))
                except RuntimeError:
                    # If no loop is running, run the emit coroutine directly using asyncio.run.
                    # This might happen if the signal is received before the loop starts or after it stops.
                    asyncio.run(shutdown_event.emit(signal_received))

            return inner

        # Signals to handle for shutdown
        signals_to_handle = [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]

        try:
            # Attempt to use asyncio's signal handling mechanism
            loop = asyncio.get_running_loop()
            for s in signals_to_handle:
                # Create a unique handler for each signal using the factory
                loop.add_signal_handler(s, handle_signal(s))
        except RuntimeError:
            # Fallback to standard signal handling if asyncio loop isn't available or
            # add_signal_handler is not supported (e.g., on Windows for some signals).
            # Note: The signature for signal.signal handler is different, it expects (signum, frame).
            # We adapt by creating a wrapper that fits the expected signature,
            # although the frame argument is not used by our inner logic.
            def signal_wrapper(
                sig_enum: signal.Signals,
            ) -> Callable[[int, Optional[inspect.FrameType]], None]:
                handler_func = handle_signal(sig_enum)

                def wrapper(signum: int, frame: Optional[inspect.FrameType]) -> None:
                    handler_func()

                return wrapper

            for s in signals_to_handle:
                # Create a unique handler that fits the signal.signal signature
                signal.signal(s, signal_wrapper(s))

    # Ensure __ON_SHUTDOWN__ is not None before returning
    if __ON_SHUTDOWN__ is None:
        # This path should theoretically not be reached due to the logic above,
        # but acts as a safeguard.
        raise RuntimeError(
            "Failed to initialize the shutdown event."
        )  # Or handle appropriately

    return __ON_SHUTDOWN__
