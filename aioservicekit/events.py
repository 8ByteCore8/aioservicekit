import asyncio
import inspect
import logging
import signal
from collections.abc import Awaitable, Coroutine
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
logger = logging.getLogger(__name__)

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


class Event(Generic[_P]):
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
        Callable[_P, None | Coroutine[Any, Any, None]]
    ]  # Set of registered listener functions

    def __init__(self) -> None:
        """
        Initialize a new Event instance.
        """
        self.__listeners__ = set()
        logger.debug("Initialized new Event instance")

    def __enter__(self) -> Self:
        """
        Enter context manager.
        Allows event to be used in 'with' statements for automatic cleanup.

        Returns:
            Self: The event instance itself.
        """
        logger.debug("Entering Event context")
        return self

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
        logger.debug("Exiting Event context")
        self.close()
        if et:
            logger.error(f"Exception occurred in Event context: {exc}", exc_info=exc)
            raise exc

    async def __emit__(self, *args: _P.args, **kwargs: _P.kwargs) -> None:
        """
        Internal method to execute all registered listeners.

        Creates an asyncio TaskGroup to run listeners concurrently.
        Handles both sync and async listeners appropriately.
        Silently catches listener exceptions to prevent cascade failures.

        Args:
            *args: Positional arguments to pass to listeners
            **kwargs: Keyword arguments to pass to listeners
        """
        logger.debug(f"Emitting event to {len(self.__listeners__)} listeners")
        async with asyncio.TaskGroup() as group:
            for listener in self.__listeners__:
                try:
                    res = listener(*args, **kwargs)
                    if inspect.isawaitable(res):
                        logger.debug(f"Running async listener {listener.__name__}")

                        async def __emit_wrapper__(coro: Awaitable) -> None:
                            try:
                                await coro
                            except Exception as e:
                                logger.error(
                                    f"Error in async listener: {e}", exc_info=e
                                )

                        group.create_task(__emit_wrapper__(res))
                    else:
                        logger.debug(f"Ran sync listener {listener.__name__}")
                except Exception as e:
                    logger.error(f"Error in listener: {e}", exc_info=e)

    @property
    def is_closed(self) -> bool:
        """
        Property indicating if event is closed.

        Returns:
            bool: True if event is closed, False otherwise
        """
        return self.__closed__

    def add_listener(
        self, listener: Callable[_P, None | Coroutine[Any, Any, None]]
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
            logger.error("Attempted to add listener to closed event")
            raise EventClosedError()

        if callable(listener):
            self.__listeners__.add(listener)
            logger.debug(f"Added listener {listener.__name__}")

    def remove_listener(
        self, listener: Callable[_P, None | Coroutine[Any, Any, None]]
    ) -> None:
        """
        Remove a previously registered listener.

        Safely removes listener from the set of registered listeners.
        No error if listener wasn't registered.

        Args:
            listener: The listener function/coroutine to remove
        """
        self.__listeners__.discard(listener)
        logger.debug(f"Removed listener {listener.__name__}")

    async def emit(self, *args: _P.args, **kwargs: _P.kwargs) -> None:
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
            logger.error("Attempted to emit on closed event")
            raise EventClosedError()
        logger.debug("Creating emit task")
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
            logger.debug("Event already closed")
            return

        self.__closed__ = True
        listener_count = len(self.__listeners__)
        self.__listeners__.clear()
        logger.debug(f"Closed event and cleared {listener_count} listeners")


__ON_SHUTDOWN__: Optional[Event[signal.Signals]] = (
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
        logger.debug("Initializing shutdown event")
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
                logger.debug(f"Received signal {signal_received.name}")
                shutdown_event = cast(Event[signal.Signals], __ON_SHUTDOWN__)
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(shutdown_event.emit(signal_received))
                except RuntimeError:
                    logger.debug("No running loop, using asyncio.run()")
                    asyncio.run(shutdown_event.emit(signal_received))

            return inner

        signals_to_handle = [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]
        logger.debug(
            f"Setting up signal handlers for {[s.name for s in signals_to_handle]}"
        )

        try:
            loop = asyncio.get_running_loop()
            for s in signals_to_handle:
                loop.add_signal_handler(s, handle_signal(s))
                logger.debug(f"Added asyncio signal handler for {s.name}")
        except RuntimeError:
            logger.debug("No running loop, using signal module handlers")
            for s in signals_to_handle:
                signal.signal(s, handle_signal(s))
                logger.debug(f"Added signal module handler for {s.name}")

    return __ON_SHUTDOWN__
