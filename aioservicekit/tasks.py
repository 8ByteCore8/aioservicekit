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
    """
    Abstract base class for defining periodic tasks.

    This class provides a framework for running a specific task (`__task__`)
    repeatedly at a defined interval. It handles the scheduling, execution,
    and error handling of the task. Subclasses must implement the `__task__`
    method to define the actual work to be performed.
    """

    _interval_: float

    def __init__(self, interval: float, *, name: Optional[str] = None) -> None:
        """
        Initialize the Task instance.

        Args:
            interval (float): The time interval in seconds between consecutive
                              runs of the `__task__` method.
            name (Optional[str]): An optional name for the service, used for logging
                                  and identification. Defaults to None.
        """
        super().__init__(name=name)
        self._interval_ = interval

    @property
    def interval(self) -> float:
        """
        The interval in seconds between task executions.

        Returns:
            float: The configured interval time.
        """
        return self._interval_

    async def _work_(self) -> None:
        """
        The main work loop for the task.

        This method runs the `__task__` coroutine and then sleeps for the
        specified `interval`. It uses `asyncio.TaskGroup` to manage the task
        and the sleep operation concurrently. If the `__task__` raises an
        exception, it emits the error using `on_error.emit` and then sleeps
        for the interval before the next attempt. It handles both single
        exceptions and `BaseExceptionGroup` (for compatibility).
        """
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self._task_())
                # Sleep concurrently with the task execution to ensure the interval
                # starts roughly when the task starts, not after it finishes.
                # If the task finishes early, the sleep continues.
                # If the sleep finishes first (task takes longer than interval),
                # the TaskGroup waits for the task to complete.
                tasks.create_task(asyncio.sleep(self.interval))
        except BaseExceptionGroup as err_group:
            # Handle potential multiple exceptions from the TaskGroup
            async with asyncio.TaskGroup() as error_tasks:
                for err in err_group.exceptions:
                    error_tasks.create_task(self.on_error.emit(err))
            # Wait for the interval after handling errors before the next cycle
            await asyncio.sleep(self._interval_)
        except BaseException as err:
            # Handle single exceptions (e.g., from __task__ directly)
            await self.on_error.emit(err)
            # Wait for the interval after handling the error before the next cycle
            await asyncio.sleep(self._interval_)

    @abstractmethod
    def _task_(self) -> Coroutine[Any, Any, None]:
        """
        The core task logic to be executed periodically.

        Subclasses must implement this method to define the actual work
        that needs to be performed in each cycle. This method should be
        a coroutine.

        Returns:
            Coroutine[Any, Any, None]: A coroutine representing the task execution.
                                       It should not return any meaningful value.
        """
        pass


class TaskFn(Task):
    """
    A concrete implementation of Task that wraps a given coroutine function.

    This class allows creating a periodic task directly from a coroutine function,
    avoiding the need to subclass `Task` explicitly for simple cases.
    """

    _task_fn_: Callable[[], Coroutine[Any, Any, None]]

    def __init__(
        self,
        fn: Callable[[], Coroutine[Any, Any, None]],
        interval: float,
        *,
        name: Optional[str] = None,
    ) -> None:
        """
        Initialize the TaskFn instance.

        Args:
            fn (Callable[[], Coroutine[Any, Any, None]]): The coroutine function
                to be executed periodically as the task.
            interval (float): The time interval in seconds between consecutive
                              runs of the provided function `fn`.
            name (Optional[str]): An optional name for the service, used for logging
                                  and identification. Defaults to None.
        """
        super().__init__(interval, name=name)
        self._task_fn_ = fn

    def _task_(self) -> Coroutine[Any, Any, None]:
        """
        Executes the wrapped coroutine function.

        This method is called periodically by the base `Task` class's work loop.
        It simply calls the coroutine function provided during initialization.

        Returns:
            Coroutine[Any, Any, None]: The coroutine returned by the wrapped function.
        """
        return self._task_fn_()


def task(
    interval: float, *, name: Optional[str] = None
) -> Callable[[Callable[[], Coroutine[Any, Any, None]]], Task]:
    """
    Decorator factory to create a periodic Task from a coroutine function.

    This function acts as a factory that returns a decorator. When the decorator
    is applied to a coroutine function, it wraps the function in a `TaskFn`
    instance, effectively creating a periodic task that runs the decorated
    function at the specified interval.

    Args:
        interval (float): The time interval in seconds between consecutive
                          runs of the decorated function.
        name (Optional[str]): An optional name for the underlying service,
                              used for logging and identification. Defaults to None.

    Returns:
        Callable[[Callable[[], Coroutine[Any, Any, None]]], Task]:
            A decorator function that takes a coroutine function and returns
            a `Task` instance.
    """

    def wrapper(func: Callable[[], Coroutine[Any, Any, None]]) -> Task:
        """
        The actual decorator that wraps the coroutine function.

        Args:
            func (Callable[[], Coroutine[Any, Any, None]]): The coroutine
                  function to be executed periodically.

        Returns:
            Task: A `TaskFn` instance configured to run the provided function
                  at the specified interval.
        """
        return TaskFn(func, interval, name=name)

    return wrapper
