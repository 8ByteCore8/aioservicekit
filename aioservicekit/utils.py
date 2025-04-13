import asyncio
from collections.abc import AsyncGenerator, Awaitable, Coroutine
from contextlib import asynccontextmanager
from typing import Any, Callable, ParamSpec, TypeVar, cast

from aioservicekit.service import Service

__all__ = ["main", "run_services"]


_P = ParamSpec("_P")
_T = TypeVar("_T")


def main(
    fn: Callable[_P, Coroutine[Any, Any, _T]],
) -> Callable[_P, Coroutine[Any, Any, _T]]:
    """
    Decorator to ensure all background asyncio tasks created by the decorated
    coroutine function complete before the function returns.

    This is useful for main entry points of applications to prevent the program
    from exiting while background tasks (like logging, monitoring, etc.)
    are still running.

    Args:
        fn: The asynchronous function to wrap.
            It can accept any arguments and should return a Coroutine yielding a value of type _T.

    Returns:
        An asynchronous wrapper function that executes the original function,
        waits for all other asyncio tasks to complete, and then returns the
        original function's result.
    """

    async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        """
        Asynchronous wrapper function that executes the decorated function and
        waits for background tasks.

        It calls the original function `fn` with the provided arguments,
        then identifies all other running asyncio tasks (excluding itself),
        waits for them to finish using `asyncio.wait`, and finally returns
        the result obtained from `fn`.

        Args:
            *args: Positional arguments to pass to the decorated function `fn`.
            **kwargs: Keyword arguments to pass to the decorated function `fn`.

        Returns:
            The result returned by the decorated function `fn`.
        """
        res = await fn(*args, **kwargs)  # type: ignore[assignment]

        # Gather all tasks currently managed by the event loop
        tasks = asyncio.all_tasks()

        # Exclude the current task (the wrapper itself) from the wait list
        if (current_task := asyncio.current_task()) is not None:
            tasks.remove(current_task)

        # Wait for all other tasks to complete if any exist
        if tasks:
            await asyncio.wait(tasks)

        return res

    return wrapper


@asynccontextmanager
async def run_services(
    services: list[Service],
) -> AsyncGenerator[Awaitable[None], Any]:
    """
    Asynchronous context manager to manage the lifecycle of a list of services.

    Starts all provided services sequentially upon entering the context. If any
    service fails to start, it attempts to stop all previously started services
    before raising the error.

    Yields an awaitable that completes when all services have finished running
    (i.e., their `wait()` methods have returned).

    Upon exiting the context (normally or due to an exception within the `with`
    block), it ensures all started services are stopped.

    Args:
        services: A list of Service instances to manage.

    Yields:
        An awaitable (typically an asyncio.Task from `asyncio.gather`) that can
        be awaited to block until all managed services have completed their
        execution.

    Raises:
        Exception: Any exception raised during the startup of a service, after
                   attempting to stop already started services.
    """
    waiters: list[Awaitable[None]] = []
    started: list[Service] = []

    try:
        for service in services:
            await service.start()
            started.append(service)
            waiters.append(service.wait())

        yield cast(Awaitable[None], asyncio.gather(*waiters))

    finally:
        # Stop services in reverse order of startup
        # This handles both normal exit and exceptions during startup/runtime
        started.reverse()
        for service in started:
            # Attempt to stop all started services regardless of errors
            # during the stop process itself (though asyncio might handle this)
            try:
                await service.stop()
            except Exception:
                # TODO: Consider logging stop errors, but don't let them
                # prevent other services from being stopped.
                pass
