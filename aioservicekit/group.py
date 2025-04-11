import asyncio
import sys
from collections.abc import Coroutine
from contextvars import Context
from inspect import Traceback
from typing import Any, Optional, Self

from aioservicekit.events import Event

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup

__all__ = [
    "TaskGroup",
]


class TaskGroup:
    """
    A utility class for managing tasks and handling errors in an asynchronous context.

    Provides a way to create, cancel, and wait for multiple tasks to complete,
    while also allowing error tolerance and notification.
    """

    on_error: Event[BaseException]

    def __init__(self, *, error_tolerance: bool = False) -> None:
        """
        Initialize the TaskGroup instance.

        Args:
            error_tolerance (bool): Whether to tolerate errors and continue execution. Defaults to False.
        """
        self._tasks_ = set()
        self._uncanceliable_tasks_ = set()
        self._errors_ = []
        self.on_error = Event()
        self._error_tolerance_ = error_tolerance

    async def __aenter__(self) -> Self:
        """
        Enter the TaskGroup context.

        Returns:
            Self: The TaskGroup instance.
        """
        return self

    async def __aexit__(
        self, et: type[Exception], exc: Exception, tb: Traceback
    ) -> None:
        """
        Exit the TaskGroup context and handle any errors that occurred during execution.

        Args:
            et (Type[Exception]): The type of exception that triggered exit.
            exc (Optional[BaseException]): The exception instance that triggered exit, or None if no exception was raised.
            tb: The traceback associated with the exception.
        """
        if exc:
            self.cancel()

        await self.wait()

        if exc:
            raise exc

    def reset_errors(self) -> None:
        """
        Reset the error list.
        """
        self._errors_ = []

    @property
    def error(self) -> list[BaseException]:
        """
        Get a list of errors that occurred during execution.

        Returns:
            list[BaseException]: A list of BaseException instances.
        """
        return [*self._errors_]

    def _on_task_done_(self, task: asyncio.Task) -> None:
        """
        Callback for when a task is done.

        Args:
            task (asyncio.Task): The completed task instance.
        """
        self._tasks_.discard(task)
        self._uncanceliable_tasks_.discard(task)

        if (error := task.exception()) is not None and not isinstance(
            error, asyncio.CancelledError
        ):
            if not self._error_tolerance_:
                self._errors_.append(error)
            asyncio.create_task(self.on_error.emit(error))

            if not self._error_tolerance_:
                self.cancel()

    def create_task(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: Optional[str] = None,
        context: Optional[Context] = None,
        canceliable: bool = True,
    ) -> asyncio.Task:
        """
        Create a new task and add it to the TaskGroup.

        Args:
            coro (Coroutine[Any, Any, Any]): The coroutine to run as a task.
            name (Optional[str], optional): The name of the task. Defaults to None.
            context (Optional[Context], optional): The context for the task. Defaults to None.
            canceliable (bool, optional): Whether the task is cancelable. Defaults to True.

        Returns:
            asyncio.Task: The created task instance.
        """
        task = asyncio.create_task(coro, name=name, context=context)
        task.add_done_callback(self._on_task_done_)

        if canceliable:
            self._tasks_.add(task)
        else:
            self._uncanceliable_tasks_.add(task)

        try:
            return task
        finally:
            # gh-128552: prevent a refcycle of
            # task.exception().__traceback__->TaskGroup.create_task->task
            del task

    def cancel(self) -> None:
        """
        Cancel all tasks in the group.
        """
        for task in self._tasks_:
            if not task.done():
                task.cancel()

    async def wait(self) -> None:
        """
        Wait for all tasks in the group to complete.

        If an error occurred during execution and error tolerance is disabled, a BaseExceptionGroup will be raised.
        """
        if all_tasks := set([*self._uncanceliable_tasks_, *self._tasks_]):
            await asyncio.wait(all_tasks)

        if self._errors_ and not self._error_tolerance_:
            raise BaseExceptionGroup(
                "unhandled errors in a TaskGroup",
                self._errors_,
            )
