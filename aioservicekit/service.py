import asyncio
import inspect
from abc import ABC, abstractmethod
from collections.abc import Coroutine
from contextvars import Context
from enum import IntEnum, auto
from typing import Any, Callable, Optional

from .events import Event, on_shutdown
from .group import TaskGroup

__all__ = ["ServiceState", "AbstractService", "service"]


class ServiceState(IntEnum):
    STARTING = auto()
    RUNNING = auto()
    STOPING = auto()
    STOPED = auto()


class AbstractService(ABC):
    """Abscract class for services"""

    __main__: Optional[asyncio.Task]
    """Main service process"""
    __name__: str
    """Service name"""
    """Service state change event"""
    __waiter__: asyncio.Event
    __state__: ServiceState
    """Service state"""
    __tasks__: TaskGroup
    on_state_change: Event[ServiceState]
    on_error: Event[BaseException]

    def __set_state__(self, state: ServiceState):
        self.__state__ = state
        return self.on_state_change.emit(state)

    @property
    def is_stoped(self) -> bool:
        """Is service running"""
        return self.__state__ == ServiceState.STOPED

    @property
    def is_running(self) -> bool:
        """Is service running"""
        return self.__state__ == ServiceState.RUNNING

    @property
    def name(self) -> str | None:
        return self.__name__

    def __init__(self, *, name: Optional[str] = None) -> None:
        """Create new service"""
        super().__init__()

        self.__name__ = name or self.__class__.__name__
        self.__main__ = None
        self.__state__ = ServiceState.STOPED
        self.__waiter__ = asyncio.Event()
        self.__tasks__ = TaskGroup(error_tolerance=True)
        self.on_error = self.__tasks__.on_error
        self.on_state_change = Event()

    def __on_shutdown__(self, *args, **kwargs):
        return self.stop()

    def create_task(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str | None = None,
        context: Context | None = None,
        canceliable: bool = True,
    ) -> asyncio.Task:
        return self.__tasks__.create_task(
            coro, name=name, context=context, canceliable=canceliable
        )

    async def start(self) -> None:
        """Start service and subscrube to shutdown event"""
        if self.is_stoped:
            self.__waiter__.clear()
            await self.__set_state__(ServiceState.STARTING)
            # Do start
            start = self.__on_start__()
            if inspect.isawaitable(start):
                await start

            # Subscrube to shutdown event
            on_shutdown().add_listener(self.__on_shutdown__)

            # Emit service start event
            await self.__set_state__(ServiceState.RUNNING)

            async def __work_wrapper__(self):
                while self.__state__ == ServiceState.RUNNING:
                    try:
                        await self.__work__()
                    except Exception as err:
                        await self.on_error.emit(self, err)

            # Run main process
            self.__main__ = asyncio.create_task(
                __work_wrapper__(self), name=self.__name__
            )

    async def wait(self) -> None:
        """Wait service end"""
        if self.is_running:
            await self.__waiter__.wait()

    async def stop(self) -> None:
        """Stop service and subscrube to shutdown event"""
        if self.is_running:
            await self.__set_state__(ServiceState.STOPING)

            # Unsubscrube from shutdown event
            _on_shutdown = on_shutdown()
            _on_shutdown.remove_listener(self.__on_shutdown__)

            # Do stop
            stop = self.__on_stop__()
            if inspect.isawaitable(stop):
                await stop

            # Wait main process complete
            if self.__main__ is not None:
                await self.__main__

            # Wait backgroud tasks
            self.__tasks__.cancel()
            await self.__tasks__.wait()

            # Mark as stoped
            self.__main__ = None
            await self.__set_state__(ServiceState.STOPED)
            self.__waiter__.set()

    async def restart(self) -> None:
        """Restart service"""
        if self.is_running:
            await self.stop()
            await self.start()

    def __on_start__(self) -> Coroutine[Any, Any, None] | None:
        """Startup initialisation"""
        return None

    @abstractmethod
    def __work__(self) -> Coroutine[Any, Any, None]:
        """Main service process"""
        pass

    def __on_stop__(self) -> Coroutine[Any, Any, None] | None:
        """Service stoping"""
        return None


class ServiceFn(AbstractService):
    __work_fn__: Callable[[], Coroutine[Any, Any, None]]

    def __init__(
        self, fn: Callable[[], Coroutine[Any, Any, None]], *, name: Optional[str] = None
    ) -> None:
        super().__init__(name=name or fn.__name__)
        self.__work_fn__ = fn

    def __work__(self) -> Coroutine[Any, Any, None]:
        return self.__work_fn__()


def service(
    *, name: Optional[str] = None
) -> Callable[[Callable[[], Coroutine[Any, Any, None]]], AbstractService]:
    def wrapper(func: Callable[[], Coroutine[Any, Any, None]]) -> AbstractService:
        return ServiceFn(func, name=name)

    return wrapper
