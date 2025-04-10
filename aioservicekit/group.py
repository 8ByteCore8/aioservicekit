import asyncio
import sys
from collections.abc import Coroutine
from contextvars import Context
from typing import Any, Optional, Self

from aioservicekit.events import Event

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup

__all__ = [
    "TaskGroup",
]


class TaskGroup:
    __tasks__: set[asyncio.Task]
    __uncanceliable_tasks__: set[asyncio.Task]
    __error_tolerance__: bool
    __errors__: list[BaseException]

    on_error: Event[BaseException]

    def __init__(self, *, error_tolerance: bool = False) -> None:
        self.__tasks__ = set()
        self.__uncanceliable_tasks__ = set()
        self.__errors__ = []
        self.on_error = Event()
        self.__error_tolerance__ = error_tolerance

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, et, exc, tb) -> None:
        if exc:
            self.cancel()

        await self.wait()

        if exc:
            raise exc

    def __on_task_done__(self, task: asyncio.Task) -> None:
        self.__tasks__.discard(task)
        self.__uncanceliable_tasks__.discard(task)

        if (error := task.exception()) is not None and not isinstance(
            error, asyncio.CancelledError
        ):
            self.__errors__.append(error)
            asyncio.create_task(self.on_error.emit(error))

            if not self.__error_tolerance__:
                self.cancel()

    def create_task(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: Optional[str] = None,
        context: Optional[Context] = None,
        canceliable: bool = True,
    ) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name, context=context)
        task.add_done_callback(self.__on_task_done__)

        if canceliable:
            self.__tasks__.add(task)
        else:
            self.__uncanceliable_tasks__.add(task)

        try:
            return task
        finally:
            # gh-128552: prevent a refcycle of
            # task.exception().__traceback__->TaskGroup.create_task->task
            del task

    def cancel(self) -> None:
        """Cancel task in group"""
        for task in self.__tasks__:
            if not task.done():
                task.cancel()

    async def wait(self) -> None:
        if all_tasks := set([*self.__uncanceliable_tasks__, *self.__tasks__]):
            await asyncio.wait(all_tasks)

        if self.__errors__ and not self.__error_tolerance__:
            raise BaseExceptionGroup(
                "unhandled errors in a TaskGroup",
                self.__errors__,
            )
