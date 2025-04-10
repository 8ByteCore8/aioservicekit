import asyncio
import inspect
import signal
from collections.abc import Coroutine
from typing import (
    Any,
    Callable,
    Generic,
    Optional,
    Self,
    TypeVarTuple,
    cast,
)

__all__ = [
    "EventError",
    "EventClosedError",
    "Event",
    "on_shutdown",
]

_ARGS = TypeVarTuple("_ARGS")


class EventError(Exception):
    pass


class EventClosedError(EventError):
    pass


class Event(Generic[*_ARGS]):
    __closed__: bool = False
    __listeners__: set[Callable[[*_ARGS], None | Coroutine[Any, Any, None]]]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __init__(self) -> None:
        self.__listeners__ = set()

    def add_listener(
        self, listener: Callable[[*_ARGS], None | Coroutine[Any, Any, None]]
    ) -> None:
        """Subscribe listener"""
        if self.__closed__:
            raise EventClosedError()

        if listener not in self.__listeners__ and callable(listener):
            self.__listeners__.add(listener)

    def remove_listener(
        self, listener: Callable[[*_ARGS], None | Coroutine[Any, Any, None]]
    ) -> None:
        """Unsubscribe listener"""
        if self.__closed__:
            raise EventClosedError()

        if listener in self.__listeners__:
            self.__listeners__.remove(listener)

    async def __emit__(self, *args: *_ARGS):
        async with asyncio.TaskGroup() as group:
            for listener in self.__listeners__:
                try:
                    res = listener(*args)
                    if inspect.isawaitable(res):
                        group.create_task(res)
                except Exception as e:
                    print(f"Listener raised an exception: {e}")

    async def emit(self, *args: *_ARGS) -> None:
        """Emit event"""
        if self.__closed__:
            raise EventClosedError()

        await asyncio.create_task(self.__emit__(*args))

    def close(self) -> None:
        """Close event and free resources"""
        if self.__closed__:
            raise EventClosedError()

        self.__closed__ = True
        self.__listeners__.clear()


__ON_SHUTDOWN__: Optional[Event[signal.Signals]] = None


def on_shutdown() -> Event[signal.Signals]:
    global __ON_SHUTDOWN__

    if __ON_SHUTDOWN__ is None:
        __ON_SHUTDOWN__ = Event[signal.Signals]()

        def handle_signal(signal: signal.Signals) -> Callable[[], None]:
            def inner():
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(cast(Event, __ON_SHUTDOWN__).emit(signal))
                except RuntimeError:
                    asyncio.run(cast(Event, __ON_SHUTDOWN__).emit(signal))

            return inner

        try:
            loop = asyncio.get_running_loop()
            for s in [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]:
                loop.add_signal_handler(s, handle_signal(s))
        except RuntimeError:
            for s in [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]:
                signal.signal(s, handle_signal(s))

    return __ON_SHUTDOWN__
