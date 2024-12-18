import asyncio
import inspect
from abc import ABC, abstractmethod
from collections.abc import Coroutine
from enum import IntEnum, auto
from typing import Any, Optional, Self

from .events import Event, on_shutdown
from .group import TaskGroup


class ServiceState(IntEnum):
    STARTING = auto()
    RUNNING = auto()
    STOPING = auto()
    STOPED = auto()


class AbstractService(ABC, TaskGroup):
    """Abscract class for services"""

    __main: Optional[asyncio.Task]
    """Main service process"""
    __name: Optional[str]
    """Service name"""
    on_state_change: Event[Self, ServiceState]
    """Service state change event"""
    __waiter: asyncio.Event
    __state: ServiceState
    """Service state"""

    def __set_state(self, state: ServiceState):
        self.__state = state
        return self.on_state_change.emit(self, state)

    @property
    def is_stoped(self) -> bool:
        """Is service running"""
        return self.__state == ServiceState.STOPED

    @property
    def is_running(self) -> bool:
        """Is service running"""
        return self.__state == ServiceState.RUNNING

    @property
    def name(self) -> str | None:
        return self.__name

    def __init__(self, *, name: Optional[str] = None) -> None:
        """Create new service"""
        super().__init__()
        self.__name = name
        self.__main = None
        self.__state = ServiceState.STOPED
        self.__waiter = asyncio.Event()
        self.on_state_change = Event()

    def __on_shutdown(self, *args, **kwargs):
        return self.stop()

    async def start(self) -> None:
        """Start service and subscrube to shutdown event"""
        if self.is_stoped:
            self.__waiter.clear()
            await self.__set_state(ServiceState.STARTING)
            # Do start
            start = self.__start__()
            if inspect.isawaitable(start):
                await start

            # Subscrube to shutdown event
            _on_shutdown = on_shutdown()
            _on_shutdown.add_listener(self.__on_shutdown)

            # Emit service start event
            await self.__set_state(ServiceState.RUNNING)

            # Run main process
            self.__main = asyncio.create_task(self.__work__(), name=self.__name)

    async def wait(self) -> None:
        """Wait service end"""
        if self.is_running:
            await self.__waiter.wait()

    async def stop(self) -> None:
        """Stop service and subscrube to shutdown event"""
        if self.is_running:
            await self.__set_state(ServiceState.STOPING)

            # Unsubscrube from shutdown event
            _on_shutdown = on_shutdown()
            _on_shutdown.remove_listener(self.__on_shutdown)

            # Do stop
            stop = self.__stop__()
            if inspect.isawaitable(stop):
                await stop

            # Wait main process complete
            await self.__main

            # Wait backgroud tasks
            TaskGroup.cancel(self)
            await TaskGroup.wait(self)

            # Mark as stoped
            self.__main = None
            await self.__set_state(ServiceState.STOPED)
            self.__waiter.set()

    async def restart(self) -> None:
        """Restart service"""
        if self.is_running:
            await self.stop()
            await self.start()

    def __start__(self) -> Coroutine[Any, Any, None] | None:
        """Startup initialisation"""
        pass

    @abstractmethod
    def __work__(self) -> Coroutine[Any, Any, None]:
        """Main service process"""
        pass

    def __stop__(self) -> Coroutine[Any, Any, None] | None:
        """Service stoping"""
        pass
