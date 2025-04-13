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

    __tasks__: set[asyncio.Task]
    __uncanceliable_tasks__: set[asyncio.Task]
    __errors__: list[BaseException]
    __error_tolerance__: bool
    on_error: Event[BaseException]

    def __init__(self, *, error_tolerance: bool = False) -> None:
        """
        Initialize the TaskGroup instance.

        Args:
            error_tolerance: Whether to tolerate errors and continue execution.
                             Defaults to False.
        """
        self.__tasks__ = set()
        self.__uncanceliable_tasks__ = set()
        self.__errors__ = []
        self.__error_tolerance__ = error_tolerance
        self.on_error = Event()

    async def __aenter__(self) -> Self:
        """
        Enter the TaskGroup context.

        Returns:
            The TaskGroup instance.
        """
        return self

    async def __aexit__(
        self, et: type[Exception], exc: Exception, tb: Traceback
    ) -> None:
        """
        Exit the TaskGroup context and handle any errors that occurred during execution.

        If the context exits with an exception, all cancellable tasks managed by
        the group are cancelled. Then waits for all tasks (cancellable and
        uncancellable) to complete. Finally, if the context exited with an exception,
        that exception is re-raised. If any tasks raised exceptions and error
        tolerance is not enabled, a `BaseExceptionGroup` containing those exceptions
        is raised after waiting.

        Args:
            et: The type of exception that triggered exit, or None.
            exc: The exception instance that triggered exit, or None.
            tb: The traceback associated with the exception, or None.
        """
        if exc:
            self.cancel()

        await self.wait()

        if exc:
            raise exc

    def reset_errors(self) -> None:
        """
        Reset the internal list of collected errors.
        """
        self.__errors__ = []

    @property
    def error(self) -> list[BaseException]:
        """
        Get a list of errors collected from tasks within the group.

        Note: If `error_tolerance` is False (the default), errors are only collected
        until the first error occurs, at which point tasks are cancelled and the
        error(s) will be raised upon exiting the context or calling `wait()`.
        If `error_tolerance` is True, all errors from completed tasks are collected.

        Returns:
            A list of BaseException instances collected from tasks.
        """
        return [*self.__errors__]

    def _on_task_done_(self, task: asyncio.Task) -> None:
        """
        Internal callback for when a task managed by the group completes.

        Removes the task from the internal tracking sets. If the task raised an
        exception (other than `asyncio.CancelledError`), it handles the error
        based on the `error_tolerance` setting, emits the `on_error` event,
        and potentially cancels remaining tasks if tolerance is off.

        Args:
            task: The completed task instance.
        """
        self.__tasks__.discard(task)
        self.__uncanceliable_tasks__.discard(task)

        if (error := task.exception()) is not None and not isinstance(
            error, asyncio.CancelledError
        ):
            # Always emit the error event, regardless of tolerance
            asyncio.create_task(self.on_error.emit(error))

            if not self.__error_tolerance__:
                self.__errors__.append(error)
                # If not tolerating errors, cancel remaining tasks upon first error
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
        Create a new task, schedule it, and add it to the TaskGroup for management.

        Args:
            coro: The coroutine to run as a task.
            name: Optional name for the task.
            context: Optional context for the task.
            canceliable: If False, the task will not be cancelled when the group
                         is cancelled (e.g., due to an error in another task when
                         `error_tolerance` is False, or explicit call to `cancel()`).
                         Defaults to True.

        Returns:
            The created `asyncio.Task` instance.
        """
        task = asyncio.create_task(coro, name=name, context=context)
        task.add_done_callback(self._on_task_done_)

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
        """
        Cancel all *cancellable* tasks currently running in the group.

        Tasks created with `canceliable=False` will not be cancelled by this method.
        """
        for task in self.__tasks__:
            if not task.done():
                task.cancel()

    async def wait(self) -> None:
        """
        Wait until all tasks (cancellable and uncancellable) in the group complete.

        If any task raised an exception and `error_tolerance` is False,
        a `BaseExceptionGroup` containing the collected error(s) will be raised
        after all tasks have finished. If `error_tolerance` is True, errors
        are collected but not raised here (they can be accessed via the `error`
        property).

        Raises:
            BaseExceptionGroup: If `error_tolerance` is False and one or more
                                tasks raised exceptions.
        """
        if all_tasks := set([*self.__uncanceliable_tasks__, *self.__tasks__]):
            await asyncio.wait(all_tasks)

        if self.__errors__ and not self.__error_tolerance__:
            # Raise only if errors occurred *and* we are not tolerating them.
            # Note: In non-tolerance mode, self.__errors__ typically contains only
            # the first error(s) that triggered cancellation.
            raise BaseExceptionGroup(
                "unhandled errors in a TaskGroup",
                self.__errors__,
            )
