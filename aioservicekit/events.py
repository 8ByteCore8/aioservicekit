import asyncio
import inspect
import signal
from typing import (
    Any,
    Callable,
    Coroutine,
    Generic,
    Optional,
    Self,
    Set,
    TypeVarTuple,
)

# Define a TypeVarTuple for variable argument types
_ARGS = TypeVarTuple("ARGS")


class EventError(Exception):
    pass


class EventClosedError(EventError):
    pass


class Event(Generic[*_ARGS]):
    __closed: bool = False
    __listeners: Set[Callable[[*_ARGS], None | Coroutine[Any, Any, None]]]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __init__(self) -> None:
        self.__listeners = set()

    def add_listener(
        self, listener: Callable[[*_ARGS], None | Coroutine[Any, Any, None]]
    ) -> None:
        """Subscribe listener"""
        if self.__closed:
            raise EventClosedError()

        if listener not in self.__listeners and callable(listener):
            self.__listeners.add(listener)

    def remove_listener(
        self, listener: Callable[[*_ARGS], None | Coroutine[Any, Any, None]]
    ) -> None:
        """Unsubscribe listener"""
        if self.__closed:
            raise EventClosedError()

        if listener in self.__listeners:
            self.__listeners.remove(listener)

    async def __emit(self, *args: *_ARGS):
        async with asyncio.TaskGroup() as group:
            for listener in self.__listeners:
                try:
                    res = listener(*args)
                    if inspect.isawaitable(res):
                        group.create_task(res)
                except Exception as e:
                    print(f"Listener raised an exception: {e}")

    async def emit(self, *args: *_ARGS) -> None:
        """Emit event"""
        if self.__closed:
            raise EventClosedError()

        await asyncio.create_task(self.__emit(*args))

    def close(self) -> None:
        """Close event and free resources"""
        if self.__closed:
            raise EventClosedError()

        self.__closed = True
        self.__listeners.clear()
        self.__listeners = None


__ON_SHUTDOWN: Optional[Event[signal.Signals]] = None


def on_shutdown() -> Event[signal.Signals]:
    global __ON_SHUTDOWN

    if __ON_SHUTDOWN is None:
        __ON_SHUTDOWN = Event[signal.Signals]()

        def handle_signal(signal: signal.Signals):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(__ON_SHUTDOWN.emit(signal))
            except RuntimeError:
                asyncio.run(__ON_SHUTDOWN.emit(signal))

        try:
            loop = asyncio.get_running_loop()
            for s in [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]:
                loop.add_signal_handler(s, handle_signal, s)
        except RuntimeError:
            for s in [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]:
                signal.signal(s, handle_signal, s)

    return __ON_SHUTDOWN
