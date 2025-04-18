import asyncio
import inspect
from abc import ABC, abstractmethod
from collections.abc import Coroutine, Sequence
from contextvars import Context
from enum import IntEnum, auto
from typing import Any, Callable, Optional, ParamSpec, Self

from .events import Event, on_shutdown
from .groups import TaskGroup

__all__ = ["ServiceState", "Service", "service"]

_P = ParamSpec("_P")


class ServiceState(IntEnum):
    """Enumeration defining the possible lifecycle states of a service."""

    STARTING = auto()
    """The service is in the process of starting up."""
    RUNNING = auto()
    """The service is actively running its main work loop."""
    STOPING = auto()
    """The service is in the process of shutting down."""
    STOPED = auto()
    """The service has completed its shutdown process and is stopped."""


class Service(ABC):
    """
    Abstract base class for creating asynchronous services.

    Provides a lifecycle management framework (start, stop, restart, wait)
    and task management capabilities for background operations.

    Attributes:
        on_state_change (Event[ServiceState]): Event triggered when the service state changes.
        on_error (Event[BaseException]): Event triggered when an unhandled exception
                                         occurs in a background task. Inherited
                                         from the internal TaskGroup.
    """

    __main__: Optional[asyncio.Task]
    __name__: str
    __waiter__: asyncio.Event
    __dependences_waiter__: asyncio.Event
    __state__: ServiceState
    __tasks__: TaskGroup
    __dependences__: Sequence["Service"]

    on_state_change: Event[ServiceState]
    """Event triggered when the service state changes."""
    on_error: Event[BaseException]
    """Event triggered when an unhandled exception occurs in a background task."""

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        dependences: Sequence["Service"] = [],
    ) -> None:
        """
        Initialize a new service instance.

        Args:
            name (Optional[str]): An optional name for the service. If None,
                                  the class name is used. Defaults to None.
            dependences (Sequence[Service]): A sequence of other services
                                                    that this service depends on.
                                                    The service will ensure these
                                                    dependencies are running before
                                                    it starts and will stop if any
                                                    dependency stops. Defaults to [].
        """
        super().__init__()
        self.__name__ = name or self.__class__.__name__
        self.__main__ = None
        self.__state__ = ServiceState.STOPED
        self.__waiter__ = asyncio.Event()
        self.__dependences_waiter__ = asyncio.Event()
        self.__tasks__ = TaskGroup(error_tolerance=True)
        self.__dependences__ = dependences
        self.on_error = self.__tasks__.on_error
        self.on_state_change = Event()

    def __set_state__(self, state: ServiceState) -> Coroutine[Any, Any, None]:
        """
        Internal method to update the service state and emit the change event.

        Args:
            state (ServiceState): The new state to set.

        Returns:
            Coroutine[Any, Any, None]: An awaitable that completes when the state
                                       change event has been emitted.
        """
        self.__state__ = state
        return self.on_state_change.emit(state)

    def __is_dependences_running__(self) -> bool:
        """
        Internal check to see if all service dependencies are running.

        Returns:
            bool: True if all dependency services are in the RUNNING state,
                  False otherwise.
        """
        return all(
            dependence.state == ServiceState.RUNNING
            for dependence in self.__dependences__
        )

    def __on_shutdown__(self, *args: Any, **kwargs: Any) -> None:
        """
        Internal handler called on application shutdown (via `on_shutdown` event)
        to initiate the service stop sequence.

        Args:
            *args: Positional arguments passed by the shutdown event.
            **kwargs: Keyword arguments passed by the shutdown event.

        Returns:
            Coroutine[Any, Any, None]: An awaitable that completes when the stop
                                       method is called.
        """
        self.stop()

    def __on_dependence_stop__(self, state: ServiceState) -> None:
        """
        Internal listener callback triggered when a dependency's state changes.

        If a dependency enters STOPING or STOPED state, this service will
        also initiate its stop sequence.

        Args:
            state (ServiceState): The new state of the dependency service.

        Returns:
            Coroutine[Any, Any, None] | None: An awaitable for the stop call if triggered,
                                            otherwise None.
        """
        if state in [ServiceState.STOPING, ServiceState.STOPED]:
            self.stop()

    def __on_dependence_running__(
        self, state: ServiceState
    ) -> Coroutine[Any, Any, None] | None:
        """
        Internal listener callback triggered when a dependency's state changes.

        Checks if all dependencies are now running. If so, signals internally
        to allow this service's startup to proceed.

        Args:
            state (ServiceState): The new state of the dependency service.

        Returns:
            Coroutine[Any, Any, None] | None: Currently always returns None, but
                                               designed for potential async operations.
        """
        if state == ServiceState.RUNNING and self.__is_dependences_running__():
            self.__dependences_waiter__.set()

    async def __work_wrapper__(self: Self) -> None:
        """
        Internal wrapper that repeatedly calls the `__work__` method.

        This runs in the main service task. It loops as long as the
        service state is RUNNING. It handles `asyncio.CancelledError` gracefully
        during stop and emits other exceptions via the `on_error` event before
        attempting to stop the service.
        """
        while self.__state__ == ServiceState.RUNNING:
            try:
                await self.__work__()
            except asyncio.CancelledError:
                # Expected cancellation when stopping the service
                break
            except Exception as err:
                # Emit unexpected errors from the work loop
                await self.on_error.emit(err)

        if self.__state__ == ServiceState.RUNNING:
            self.stop()

    @property
    def state(self) -> ServiceState:
        return self.__state__

    @property
    def run(self) -> bool:
        return self.__state__ == ServiceState.RUNNING

    @property
    def name(self) -> str:
        return self.__name__

    def create_task(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str | None = None,
        context: Context | None = None,
        canceliable: bool = True,
    ) -> asyncio.Task:
        return self.__tasks__.create_task(
            coro, name=name, context=context, canceliable=canceliable
        )

    async def start(self) -> None:
        if self.__state__ == ServiceState.STOPED:
            self.__waiter__.clear()
            await self.__set_state__(ServiceState.STARTING)
            self.__tasks__.reset_errors()

            # Setup dependency waiting
            if self.__dependences__:
                # Add listeners *before* starting dependencies
                for dependence in self.__dependences__:
                    dependence.on_state_change.add_listener(
                        self.__on_dependence_running__
                    )
                    dependence.on_state_change.add_listener(self.__on_dependence_stop__)

                if not self.__is_dependences_running__():
                    self.__dependences_waiter__.clear()

                    # Start dependencies (if not already running, start is idempotent)
                    # Use asyncio.gather for concurrent startup

                    await asyncio.gather(
                        *(dependence.start() for dependence in self.__dependences__)
                    )
                else:
                    self.__dependences_waiter__.set()  # Already running

                # Wait for all dependencies to signal they are running
                await self.__dependences_waiter__.wait()
            else:
                # No dependencies, proceed immediately
                self.__dependences_waiter__.set()

            # Execute the user-defined start hook
            start_hook = self.__on_start__()
            if inspect.isawaitable(start_hook):
                await start_hook

            # Subscribe to application shutdown
            on_shutdown().add_listener(self.__on_shutdown__)

            # Transition to RUNNING state
            await self.__set_state__(ServiceState.RUNNING)

            # Start the main work loop
            self.__main__ = asyncio.create_task(
                self.__work_wrapper__(), name=f"{self.__name__}-work"
            )

    async def wait(self) -> None:
        """
        Wait until the service has fully stopped.

        Blocks asynchronously until the service transitions to the STOPED state.
        If the service is already STOPED, returns immediately.
        Useful for ensuring a service has shut down cleanly.
        """
        if self.__state__ != ServiceState.STOPED:
            await self.__waiter__.wait()

    async def __stop__(self) -> None:
        await self.__set_state__(ServiceState.STOPING)
        # Clean up dependency listeners

        for dependence in self.__dependences__:
            dependence.on_state_change.remove_listener(self.__on_dependence_stop__)
            dependence.on_state_change.remove_listener(self.__on_dependence_running__)

        # Unsubscribe from application shutdown
        on_shutdown().remove_listener(self.__on_shutdown__)

        # Cancel main task first (if it exists and is running)
        if self.__main__ and not self.__main__.done():
            try:
                # Wait for the main task to finish handling cancellation
                await self.__main__
            except asyncio.CancelledError:
                pass  # Expected cancellation
            except Exception as err:
                # Log error during main task cleanup if needed
                await self.on_error.emit(err)
        self.__main__ = None  # Clear the reference

        # Cancel and wait for all background tasks in the group
        self.__tasks__.cancel()
        await self.__tasks__.wait()

        # Execute the user-defined stop hook
        stop_hook = self.__on_stop__()
        if inspect.isawaitable(stop_hook):
            await stop_hook

        # Mark as fully stopped
        await self.__set_state__(ServiceState.STOPED)
        self.__waiter__.set()  # Signal anyone waiting for stop completion

    def stop(self) -> None:
        """
        Stop the service gracefully.

        Transitions the service state to STOPING.
        Executes the `__on_stop__` hook, unsubscribes from the global shutdown event,
        removes dependency listeners, cancels the main `__work__` task and all
        background tasks managed by the service's TaskGroup, and waits for them
        to complete. Finally, transitions the state to STOPED and signals when
        the stop process is complete.
        Does nothing if the service is not currently RUNNING or STARTING.
        """
        if self.__state__ == ServiceState.RUNNING:
            self.__state__ = ServiceState.STOPING
            asyncio.create_task(self.__stop__())

    async def restart(self) -> None:
        """
        Restart the service.

        Convenience method that calls `stop()` followed by `start()`.
        Ensures the service is fully stopped before attempting to start again.
        """
        if self.__state__ == ServiceState.RUNNING:
            self.stop()
            await self.wait()
        await self.start()

    def __on_start__(self) -> Coroutine[Any, Any, None] | None:
        """
        Optional hook executed during the service startup phase (`start` method).

        This method is called after dependencies are running (if any) but before
        the main `__work__` loop begins and before the state transitions to RUNNING.
        Subclasses can override this to perform asynchronous initialization
        (e.g., connecting to databases, setting up resources).

        It can be a regular method (return None) or an async method (return a coroutine).

        Returns:
            Coroutine[Any, Any, None] | None: An awaitable if async initialization
                                               is performed, otherwise None.
        """
        return None

    @abstractmethod
    async def __work__(self) -> None:
        """
        Main service logic execution coroutine.

        This abstract method **must** be implemented by subclasses. It contains
        the core logic that the service performs. It will be called
        repeatedly as long as the service is in the RUNNING state.

        If this method raises an exception, it will be caught, emitted via the
        `on_error` event, and the loop will continue (unless the service is stopped).

        If the service needs to stop based on its internal logic, it should
        call `await self.stop()`. If `__work__` completes normally (returns),
        the service will also initiate a stop.

        This method *should* be awaitable (`async def`).

        Returns:
            None: This method should typically not return a meaningful value,
                  as it's run in a loop. Returning signals the loop should end.
        """
        pass  # pragma: no cover

    def __on_stop__(self) -> Coroutine[Any, Any, None] | None:
        """
        Optional hook executed during the service stopping phase (`stop` method).

        This method is called after the main `__work__` task has been cancelled
        and after background tasks managed by the service's TaskGroup are
        cancelled and awaited. Subclasses can override this to perform
        asynchronous cleanup logic (e.g., closing connections, releasing resources).

        It can be a regular method (return None) or an async method (return a coroutine).
        Exceptions raised here will be emitted via the `on_error` event.

        Returns:
            Coroutine[Any, Any, None] | None: An awaitable if async cleanup
                                               is performed, otherwise None.
        """
        return None


class FnService(Service):
    """
    Concrete implementation of Service that wraps an asynchronous function
    to serve as the main work loop (`__work__` method).

    This provides a convenient way to create simple services, especially using the
    `@service` decorator, without needing to define a full subclass of `Service`.
    """

    __work_fn__: Callable[..., Coroutine[Any, Any, None]]
    __args__: tuple
    __kwargs__: dict

    def __init__(
        self,
        fn: Callable[..., Coroutine[Any, Any, None]],
        args: tuple,
        kwargs: dict,
        *,
        name: Optional[str] = None,
        dependences: Sequence[Service] = [],
    ) -> None:
        """
        Initialize the FnService instance.

        Args:
            fn (Callable[..., Coroutine[Any, Any, None]]): The asynchronous function
                that will serve as the main work loop (`__work__` method).
            args (tuple): Positional arguments to pass to `fn` on each call.
            kwargs (dict): Keyword arguments to pass to `fn` on each call.
            name (Optional[str]): An optional name for the service. If None,
                                  the name of the provided function is used.
                                  Defaults to None.
            dependences (Sequence[Service]): A sequence of other services
                                                    that this service depends on.
                                                    Defaults to [].
        """
        super().__init__(name=name or fn.__name__, dependences=dependences)
        self.__work_fn__ = fn
        self.__args__ = args
        self.__kwargs__ = kwargs

    async def __work__(self) -> None:
        """
        Execute one cycle of the service's work by calling the wrapped function.

        This method calls the asynchronous function provided during initialization,
        passing the stored arguments.

        Returns:
            None: Mirrors the expected return of the wrapped function in the context
                  of the service work loop.
        """
        await self.__work_fn__(*self.__args__, **self.__kwargs__)


def service(
    *,
    name: Optional[str] = None,
    dependences: Sequence[Service] = [],
) -> Callable[[Callable[_P, Coroutine[Any, Any, None]]], Callable[_P, Service]]:
    """
    Decorator factory to create an `Service` instance from an async function.

    This allows defining a service's main work loop as a simple async function
    decorated with `@service(...)`. The decorated function will be wrapped in a
    `FnService` instance.

    Args:
        name (Optional[str]): An optional name for the service. If None,
                              the name of the decorated function will be used.
                              Defaults to None.
        dependences (Sequence[Service]): A sequence of other service instances
                                                 that the created service should
                                                 depend on. Defaults to [].

    Returns:
        Callable[[Callable[_P, Coroutine[Any, Any, None]]], Callable[_P, Service]]:
            A decorator function. When this decorator is applied to an async function,
            it returns a *factory function*. This factory function, when called with
            the original function's arguments, creates and returns the actual
            `FnService` instance.
    """

    def wrapper(
        func: Callable[_P, Coroutine[Any, Any, None]],
    ) -> Callable[_P, Service]:
        """
        The actual decorator that takes the async function.

        Args:
            func (Callable[_P, Coroutine[Any, Any, None]]): The asynchronous
                function to be wrapped as the service's main work loop. It can
                accept arguments.

        Returns:
            Callable[_P, Service]: A factory function that, when called
                with arguments matching `func`'s signature, creates and returns
                a configured `FnService` instance.
        """

        def inner(*args: _P.args, **kwargs: _P.kwargs) -> Service:
            """
            Factory function returned by the decorator.

            Captures the arguments intended for the original decorated function
            and creates the `FnService` instance, passing the original function,
            captured arguments, and decorator parameters (`name`, `dependences`).

            Args:
                *args: Positional arguments intended for the original `func`.
                **kwargs: Keyword arguments intended for the original `func`.

            Returns:
                Service: An instance of `FnService` configured with the
                                 provided function, arguments, name, and dependencies.
            """
            return FnService(func, args, kwargs, name=name, dependences=dependences)

        # Preserve original function signature if possible (helps with introspection/docs)
        # functools.wraps might be useful here if inner needed func's metadata,
        # but here inner *returns* the service, it doesn't replace func directly.
        # Copying __signature__ might be an option for more advanced cases.

        return inner

    return wrapper
