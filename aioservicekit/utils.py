import asyncio
from collections.abc import Coroutine
from typing import Any, Callable, ParamSpec, TypeVar

__all__ = ["safe_main"]


_P = ParamSpec("_P")
_T = TypeVar("_T")


def safe_main(
    fn: Callable[_P, Coroutine[Any, Any, _T]],
) -> Callable[_P, Coroutine[Any, Any, _T]]:
    """
    Decorator to ensure all background asyncio tasks created by the decorated
    coroutine function complete before the function returns.

    This is useful for main entry points of applications to prevent the program
    from exiting while background tasks (like logging, monitoring, etc.)
    are still running.

    Args:
        fn (Callable[[...], Coroutine[Any, Any, _T]]): The asynchronous function to wrap.
            It can accept any arguments and should return a Coroutine yielding a value of type _T.

    Returns:
        Callable[[...], Coroutine[Any, Any, _T]]: An asynchronous wrapper function that
        executes the original function, waits for all other asyncio tasks to complete,
        and then returns the original function's result.
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
            _T: The result returned by the decorated function `fn`.
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


@safe_main
async def t(x: int):
    pass
