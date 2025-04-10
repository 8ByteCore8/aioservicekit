import asyncio
import sys
from abc import abstractmethod
from collections.abc import Coroutine
from typing import Any, Callable, Optional

from aioservicekit.service import AbstractService

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup

__all__ = ["Task", "task"]


class Task(AbstractService):
    __interval__: float

    @property
    def interval(self) -> float:
        return self.__interval__

    def __init__(self, interval: float, *, name: Optional[str] = None) -> None:
        super().__init__(name=name)
        self.__interval__ = interval

    async def __work__(self) -> None:
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self.__task__())
                tasks.create_task(asyncio.sleep(self.interval))
                tasks.create_task(self.__tasks__.wait())
        except BaseExceptionGroup as err_grop:
            async with asyncio.TaskGroup() as tasks:
                for err in err_grop.exceptions:
                    tasks.create_task(self.on_error.emit(err))

    @abstractmethod
    def __task__(self) -> Coroutine[Any, Any, None]:
        """Task process"""
        pass


class TaskFn(Task):
    __task_fn__: Callable[[], Coroutine[Any, Any, None]]

    def __init__(
        self,
        fn: Callable[[], Coroutine[Any, Any, None]],
        interval: float,
        *,
        name: Optional[str] = None,
    ) -> None:
        super().__init__(interval, name=name)
        self.__task_fn__ = fn

    def __task__(self) -> Coroutine[Any, Any, None]:
        return self.__task_fn__()


def task(
    interval: float, *, name: Optional[str] = None
) -> Callable[[Callable[[], Coroutine[Any, Any, None]]], Task]:
    def wrapper(func: Callable[[], Coroutine[Any, Any, None]]) -> Task:
        return TaskFn(func, interval, name=name)

    return wrapper
