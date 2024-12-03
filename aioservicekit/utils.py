import asyncio
from collections.abc import Coroutine
from typing import Any, Callable, TypeVar

_T = TypeVar("T")


def safe_main(
    fn: Callable[[...], Coroutine[Any, Any, _T]],  # type: ignore
) -> Callable[[...], Coroutine[Any, Any, _T]]:  # type: ignore
    async def wrapper(*args, **kwargs):
        res = await fn(*args, **kwargs)

        tasks = asyncio.all_tasks()
        tasks.remove(asyncio.current_task())
        await asyncio.wait(tasks)
        return res

    return wrapper
