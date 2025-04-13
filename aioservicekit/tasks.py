import asyncio
import sys
from abc import abstractmethod
from collections.abc import Coroutine, Sequence
from typing import Any, Callable, Optional, ParamSpec

from aioservicekit.service import Service

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup

__all__ = ["Task", "task"]

_P = ParamSpec("_P")


class Task(Service):
    """
    Abstract base class for defining periodic tasks.

    This class provides a framework for running a specific task (`__task__`)
    repeatedly at a defined interval. It handles the scheduling, execution,
    and error handling of the task. Subclasses must implement the `__task__`
    method to define the actual work to be performed.
    """

    __interval__: float

    def __init__(
        self,
        interval: float,
        *,
        name: Optional[str] = None,
        dependences: Sequence[Service] = [],
    ) -> None:
        """
        Initialize the Task instance.

        Args:
            interval: The time interval in seconds between consecutive
                runs of the `__task__` method.
            name: An optional name for the service, used for logging
                and identification. Defaults to None.
            dependences: A sequence of services that this service depends on.
        """
        super().__init__(name=name, dependences=dependences)
        self.__interval__ = interval

    @property
    def interval(self) -> float:
        """
        The interval in seconds between task executions.

        Returns:
            The configured interval time.
        """
        return self.__interval__

    async def __work__(self) -> None:
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
                tasks.create_task(self.__task__())
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
            await asyncio.sleep(self.__interval__)
        except BaseException as err:
            # Handle single exceptions (e.g., from __task__ directly)
            await self.on_error.emit(err)
            # Wait for the interval after handling the error before the next cycle
            await asyncio.sleep(self.__interval__)

    @abstractmethod
    def __task__(self) -> Coroutine[Any, Any, None]:
        """
        The core task logic to be executed periodically.

        Subclasses must implement this method to define the actual work
        that needs to be performed in each cycle. This method should be
        a coroutine.

        Returns:
            A coroutine representing the task execution.
            It should not return any meaningful value.
        """
        pass


class FnTask(Task):
    """
    A concrete implementation of Task that wraps a given coroutine function.

    This class allows creating a periodic task directly from a coroutine function,
    avoiding the need to subclass `Task` explicitly for simple cases.
    """

    __task_fn__: Callable[..., Coroutine[Any, Any, None]]
    __args__: tuple
    __kwargs__: dict

    def __init__(
        self,
        fn: Callable[..., Coroutine[Any, Any, None]],
        args: tuple,
        kwargs: dict,
        interval: float,
        *,
        name: Optional[str] = None,
        dependences: Sequence[Service] = [],
    ) -> None:
        """
        Initialize the FnTask instance.

        Args:
            fn: The coroutine function to be executed periodically as the task.
            args: Positional arguments to pass to the task function.
            kwargs: Keyword arguments to pass to the task function.
            interval: The time interval in seconds between consecutive
                runs of the provided function `fn`.
            name: An optional name for the service, used for logging
                and identification. Defaults to None.
            dependences: A sequence of services that this service depends on.
        """
        super().__init__(interval, name=name, dependences=dependences)
        self.__task_fn__ = fn
        self.__args__ = args
        self.__kwargs__ = kwargs

    def __task__(self) -> Coroutine[Any, Any, None]:
        """
        Executes the wrapped coroutine function.

        This method is called periodically by the base `Task` class's work loop.
        It simply calls the coroutine function provided during initialization
        with the stored arguments.

        Returns:
            The coroutine returned by the wrapped function.
        """
        return self.__task_fn__(*self.__args__, **self.__kwargs__)


def task(
    interval: float,
    *,
    name: Optional[str] = None,
    dependences: Sequence[Service] = [],
) -> Callable[[Callable[_P, Coroutine[Any, Any, None]]], Callable[_P, Task]]:
    """
    Decorator factory to create a periodic Task from a coroutine function.

    This function acts as a factory that returns a decorator. When the decorator
    is applied to a coroutine function, it wraps the function call in a `FnTask`
    instance upon invocation, effectively creating a periodic task factory that
    runs the decorated function with its call arguments at the specified interval.

    Args:
        interval: The time interval in seconds between consecutive
            runs of the decorated function.
        name: An optional name for the underlying service,
            used for logging and identification. Defaults to None.
        dependences: A sequence of services that the created task service
            will depend on.

    Returns:
        A decorator function that takes a coroutine function and returns
        a callable. This callable, when invoked with arguments matching the
        decorated function's signature, returns a `Task` instance.
    """

    def wrapper(func: Callable[_P, Coroutine[Any, Any, None]]) -> Callable[_P, Task]:
        """
        The actual decorator that wraps the coroutine function.

        Args:
            func: The coroutine function to be executed periodically.

        Returns:
            A callable that accepts the arguments for `func` and returns a
            `FnTask` instance configured to run the provided function
            at the specified interval with those arguments.
        """

        def inner(*args: _P.args, **kwargs: _P.kwargs) -> Task:
            """
            Creates a FnTask instance when the decorated function is called.

            Args:
                *args: Positional arguments for the decorated function.
                **kwargs: Keyword arguments for the decorated function.

            Returns:
                A FnTask instance.
            """
            return FnTask(
                func, args, kwargs, interval, name=name, dependences=dependences
            )

        return inner

    return wrapper
