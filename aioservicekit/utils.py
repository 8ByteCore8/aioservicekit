import asyncio
from collections.abc import Coroutine
from typing import Any, Callable, TypeVar

__all__ = ["safe_main"]

_T = TypeVar("_T")


def safe_main(
    fn: Callable[[...], Coroutine[Any, Any, _T]],  # type: ignore
) -> Callable[[...], Coroutine[Any, Any, _T]]:  # type: ignore
    async def wrapper(*args, **kwargs):
        res = await fn(*args, **kwargs)

        tasks = asyncio.all_tasks()

        if (current_task := asyncio.current_task()) is not None:
            tasks.remove(current_task)
        await asyncio.wait(tasks)
        return res

    return wrapper
