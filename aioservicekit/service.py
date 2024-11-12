import asyncio
from abc import ABC, abstractmethod
from enum import IntEnum, auto
import inspect

from .group import TaskGroup
from .events import on_shutdown, Event
from typing import Any, Callable, Coroutine, Optional, Self


class ServiceState(IntEnum):
    STARTING = auto()
    RUNNING = auto()
    STOPING = auto()
    STOPED = auto()


class AbscractService(ABC, TaskGroup):
    """Abscract class for services"""

    __main: asyncio.Task = None
    """Main service process"""
    __name: Optional[str] = None
    """Service name"""
    __on_state_change: Event[Self, ServiceState] = Event()
    """Service state change event"""
    __waiter: asyncio.Event
    __state: ServiceState
    """Service state"""

    def __set_state(self, state: ServiceState):
        self.__state = state
        return self.__on_state_change.emit(self, state)

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
        self.__state = ServiceState.STOPED
        self.__waiter = asyncio.Event()

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

    def subscribe(
        self, callback: Callable[[Self, ServiceState], None | Coroutine[Any, Any, None]]
    ):
        """Subscribe to service events"""
        self.__on_state_change.add_listener(callback)

    def unsubscribe(self, callback: Callable[[Self], None | Coroutine[Any, Any, None]]):
        """Unsubscribe from service events"""
        self.__on_state_change.remove_listener(callback)

    @abstractmethod
    def __start__(self) -> Coroutine[Any, Any, None] | None:
        """Startup initialisation"""
        pass

    @abstractmethod
    def __work__(self) -> Coroutine[Any, Any, None]:
        """Main service process"""
        pass

    @abstractmethod
    def __stop__(self) -> Coroutine[Any, Any, None] | None:
        """Service stoping"""
        pass
