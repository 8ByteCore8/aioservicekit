import asyncio
import inspect
import signal
from collections.abc import Callable, Coroutine
from typing import (
    Any,
    Generic,
    ParamSpec,
    Self,
    cast,
)

__P__ = ParamSpec("__P__")

__all__ = [
    "EventClosedError",
    "Event",
    "on_shutdown",
]


class EventClosedError(Exception):
    """
    Exception raised when attempting to perform operations on a closed event.
    This includes adding listeners or emitting events after close() is called.
    """

    pass


class Event(Generic[__P__]):
    """
    Event class that allows registering listeners and emitting events.

    This class implements the observer pattern, allowing functions to subscribe
    to events and be notified when those events occur. It supports both
    synchronous and asynchronous listeners and can be used as a context manager.

    Type Args:
        _P: ParamSpec that defines the argument types that registered listeners
            must accept. This ensures type safety between emitters and listeners.
    """

    __closed__: bool = False  # Flag indicating if event is closed
    __listeners__: set[
        Callable[__P__, None | Coroutine[Any, Any, None]]
    ]  # Set of registered listener functions

    def __init__(self) -> None:
        """
        Initialize a new Event instance.
        """
        self.__listeners__ = set()

    def __call__(
        self, *args: __P__.args, **kwargs: __P__.kwargs
    ) -> Coroutine[Any, Any, None]:
        """
        Emit the event with the given arguments.

        Args:
            *args: Positional arguments to pass to listeners
            **kwargs: Keyword arguments to pass to listeners
        """
        return self.emit(*args, **kwargs)

    def __enter__(self) -> Self:
        """
        Enter context manager.
        Allows event to be used in 'with' statements for automatic cleanup.

        Returns:
            Self: The event instance itself.
        """
        return self

    async def __aenter__(self) -> Self:
        return self.__enter__()

    def __exit__(
        self, et: type[Exception], exc: Exception, tb: inspect.Traceback
    ) -> None:
        """
        Exit context manager and ensure event is closed.

        Args:
            et: Exception type if an error occurred
            exc: Exception instance if an error occurred
            tb: Traceback if an error occurred
        """
        self.close()
        if et:
            raise exc

    async def __aexit__(
        self, et: type[Exception], exc: Exception, tb: inspect.Traceback
    ) -> None:
        """
        Exit context manager and ensure event is closed.

        Args:
            et: Exception type if an error occurred
            exc: Exception instance if an error occurred
            tb: Traceback if an error occurred
        """
        return self.__exit__(et, exc, tb)

    def __len__(self) -> int:
        return len(self.__listeners__)

    @staticmethod
    async def __async_emit_wrapper__(coro: Coroutine[Any, Any, None]) -> None:
        try:
            await coro
        except Exception:
            pass

    async def __emit__(self, *args: __P__.args, **kwargs: __P__.kwargs) -> None:
        """
        Internal method to execute all registered listeners.

        Creates an asyncio TaskGroup to run listeners concurrently.
        Handles both sync and async listeners appropriately.
        Silently catches listener exceptions to prevent cascade failures.

        Args:
            *args: Positional arguments to pass to listeners
            **kwargs: Keyword arguments to pass to listeners
        """
        async with asyncio.TaskGroup() as group:
            for listener in self.__listeners__:
                try:
                    res = listener(*args, **kwargs)
                    if inspect.isawaitable(res):
                        group.create_task(self.__async_emit_wrapper__(res))
                except Exception:
                    pass

    @property
    def is_closed(self) -> bool:
        """
        Property indicating if event is closed.

        Returns:
            bool: True if event is closed, False otherwise
        """
        return self.__closed__

    def add_listener(
        self, listener: Callable[__P__, None | Coroutine[Any, Any, None]]
    ) -> None:
        """
        Register a new listener function or coroutine.

        The listener can be either a regular function or an async function.
        When the event is emitted, the listener will be called with the emit arguments.

        Args:
            listener: Function or coroutine to register as a listener

        Raises:
            EventClosedError: If the event has been closed
        """
        if self.__closed__:
            raise EventClosedError()

        if callable(listener):
            self.__listeners__.add(listener)

    def __iadd__(
        self, listener: Callable[__P__, None | Coroutine[Any, Any, None]]
    ) -> None:
        self.add_listener(listener)

    def remove_listener(
        self, listener: Callable[__P__, None | Coroutine[Any, Any, None]]
    ) -> None:
        """
        Remove a previously registered listener.

        Safely removes listener from the set of registered listeners.
        No error if listener wasn't registered.

        Args:
            listener: The listener function/coroutine to remove
        """
        self.__listeners__.discard(listener)

    def __isub__(
        self, listener: Callable[__P__, None | Coroutine[Any, Any, None]]
    ) -> None:
        self.remove_listener(listener)

    def has_listener(
        self, listener: Callable[__P__, None | Coroutine[Any, Any, None]]
    ) -> bool:
        return listener in self.__listeners__

    def __contains__(
        self, listener: Callable[__P__, None | Coroutine[Any, Any, None]]
    ) -> bool:
        return self.has_listener(listener)

    async def emit(self, *args: __P__.args, **kwargs: __P__.kwargs) -> None:
        """
        Emit an event to all registered listeners.

        Calls all registered listeners with the provided arguments.
        Async listeners are run concurrently in an asyncio TaskGroup.
        Exceptions in listeners are caught and ignored.

        Args:
            *args: Positional arguments to pass to listeners
            **kwargs: Keyword arguments to pass to listeners

        Raises:
            EventClosedError: If the event has been closed
        """
        if self.__closed__:
            raise EventClosedError()
        await asyncio.create_task(self.__emit__(*args, **kwargs))

    def close(self) -> None:
        """
        Close the event and prevent further operations.

        After closing:
        - No new listeners can be added
        - Events cannot be emitted
        - All registered listeners are cleared

        This operation is idempotent - calling multiple times has no effect.
        """
        if self.__closed__:
            return

        self.__closed__ = True
        self.__listeners__.clear()


__ON_SHUTDOWN__: Event[signal.Signals] | None = (
    None  # Global singleton for shutdown event
)


def on_shutdown() -> Event[signal.Signals]:
    """
    Get or create the global shutdown event handler.

    This function manages a singleton Event instance that handles system shutdown signals.
    It sets up handlers for SIGHUP, SIGTERM, and SIGINT signals.
    The event is emitted with the signal number when a shutdown signal is received.

    The implementation tries to use asyncio's signal handling, falling back to standard
    signal module if no event loop is running.

    Returns:
        Event[signal.Signals]: The singleton shutdown event instance

    Raises:
        RuntimeError: If event initialization fails
    """
    global __ON_SHUTDOWN__

    if __ON_SHUTDOWN__ is None:
        __ON_SHUTDOWN__ = Event[signal.Signals]()

        def handle_signal(signal_received: signal.Signals) -> Callable[..., None]:
            """
            Create a signal handler for a specific signal.

            Factory function that creates a closure capturing the signal type.

            Args:
                signal_received: The signal number being handled

            Returns:
                Callable: The handler function for this signal
            """

            def inner(*args, **kwargs) -> None:
                """
                Handler function called when signal is received.

                Emits the shutdown event with the signal number.
                Attempts to use running event loop or falls back to asyncio.run().

                Args:
                    *args: Signal handler positional args (unused)
                    **kwargs: Signal handler keyword args (unused)
                """
                shutdown_event = cast(Event[signal.Signals], __ON_SHUTDOWN__)
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(shutdown_event.emit(signal_received))
                except RuntimeError:
                    asyncio.run(shutdown_event.emit(signal_received))

            return inner

        signals_to_handle = [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]

        try:
            loop = asyncio.get_running_loop()
            for s in signals_to_handle:
                loop.add_signal_handler(s, handle_signal(s))
        except RuntimeError:
            for s in signals_to_handle:
                signal.signal(s, handle_signal(s))

    return __ON_SHUTDOWN__
