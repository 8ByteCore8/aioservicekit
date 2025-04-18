import asyncio
from collections.abc import Coroutine
from enum import IntEnum, auto
from inspect import Traceback, isawaitable
from typing import Any, Generic, Optional, Self, TypeVar

from aioservicekit.events import Event

__all__ = [
    "Channel",
    "ChannelClosedError",
    "_ChannelSubscriber",
    "_ChannelPublisher",
]


_T = TypeVar("_T")  # Generic type variable for channel data


class ChannelClosedError(Exception):
    """Raised when attempting to use a closed channel."""

    pass


class ChannelState(IntEnum):
    """Enum representing possible states of a Channel."""

    initiation = auto()  # Initial state when channel is created
    open = auto()  # Channel is open and can send/receive data
    closed = auto()  # Channel is closed and cannot be used


class Channel(Generic[_T]):
    """
    An asynchronous channel that supports multiple publishers and subscribers.

    Enables async communication between publishers and subscribers with optional buffering.
    """

    __subscribers__: set["_ChannelSubscriber[_T]"]  # Set of subscriber instances
    __publishers__: set["_ChannelPublisher[_T]"]  # Set of publisher instances
    __buffer_size__: int  # Maximum size of subscriber buffers
    __state__: ChannelState  # Current state of the channel

    on_state_change: Event[ChannelState]  # Event emitted when channel state changes

    def __init__(self, buffer_size: int = 0) -> None:
        """
        Initialize a new Channel.

        Args:
            buffer_size: Maximum number of messages each subscriber can buffer. 0 for unlimited.
        """
        super().__init__()
        self.__subscribers__ = set()
        self.__publishers__ = set()
        self.__buffer_size__ = buffer_size
        self.__state__ = ChannelState.initiation
        self.on_state_change = Event()

    def __set_state__(self, state: ChannelState) -> Coroutine[Any, Any, None]:
        """Set channel state and emit state change event."""
        self.__state__ = state
        return self.on_state_change.emit(state)

    async def __validate_chanel_state__(self) -> None:
        """
        Validate and update channel state based on number of publishers and subscribers.
        Opens channel when both publishers and subscribers exist.
        Closes channel when either publishers or subscribers are empty.
        """
        if self.__state__ == ChannelState.initiation and (
            len(self.__publishers__) > 0 and len(self.__subscribers__) > 0
        ):
            await self.__set_state__(ChannelState.open)
        elif self.__state__ == ChannelState.open and (
            len(self.__publishers__) == 0 or len(self.__subscribers__) == 0
        ):
            await self.__set_state__(ChannelState.closed)

    async def __send__(self, data: _T) -> None:
        """Send data to all subscribers in parallel using task groups."""
        if self.__state__ == ChannelState.closed:
            raise ChannelClosedError()

        async with asyncio.TaskGroup() as group:
            for customer in self.__subscribers__:
                if isawaitable(res := customer.__send__(data)):
                    group.create_task(res)

    async def __disconnect_subscriber__(
        self, subscriber: "_ChannelSubscriber[_T]"
    ) -> None:
        """Remove subscriber and cleanup its resources."""
        self.__subscribers__.discard(subscriber)
        self.on_state_change.remove_listener(subscriber.__on_channel_state_change__)
        asyncio.create_task(subscriber.close())
        await self.__validate_chanel_state__()

    async def __disconnect_publisher__(
        self, publisher: "_ChannelPublisher[_T]"
    ) -> None:
        """Remove publisher and cleanup its resources."""
        self.__publishers__.discard(publisher)
        self.on_state_change.remove_listener(publisher.__on_channel_state_change__)
        asyncio.create_task(publisher.close())
        await self.__validate_chanel_state__()

    async def __aenter__(self) -> Self:
        """Context manager entry."""
        return self

    async def __aexit__(
        self, et: type[Exception], exc: Exception, tb: Traceback
    ) -> None:
        """Context manager exit with cleanup."""
        await self.close()
        if exc and et != ChannelClosedError:
            raise exc

    @property
    def state(self) -> ChannelState:
        """Get current channel state."""
        return self.__state__

    async def close(self):
        """Close an open channel."""
        if self.__state__ == ChannelState.open:
            await self.__set_state__(ChannelState.closed)

    async def subscribe(
        self, *, buffer_size: Optional[int] = None
    ) -> "_ChannelSubscriber[_T]":
        """
        Create new subscriber for this channel.

        Args:
            buffer_size: Override default buffer size for this subscriber.

        Returns:
            New subscriber instance.

        Raises:
            ChannelClosedError: If channel is closed
        """
        if self.__state__ == ChannelState.closed:
            raise ChannelClosedError()

        subscriber = _ChannelSubscriber(
            self,
            buffer_size=self.__buffer_size__ if buffer_size is None else buffer_size,
        )

        self.__subscribers__.add(subscriber)
        self.on_state_change.add_listener(subscriber.__on_channel_state_change__)

        if self.__state__ == ChannelState.initiation:
            await self.__validate_chanel_state__()

        return subscriber

    async def connect(self) -> "_ChannelPublisher[_T]":
        """
        Create new publisher for this channel.

        Returns:
            New publisher instance.

        Raises:
            ChannelClosedError: If channel is closed
        """
        if self.__state__ == ChannelState.closed:
            raise ChannelClosedError()

        publisher = _ChannelPublisher(self)

        self.__publishers__.add(publisher)
        self.on_state_change.add_listener(publisher.__on_channel_state_change__)

        if self.__state__ == ChannelState.initiation:
            await self.__validate_chanel_state__()

        if self.__state__ == ChannelState.initiation:
            asyncio.create_task(self.__validate_chanel_state__())

        return publisher


class _ChannelSubscriber(Generic[_T]):
    """
    Internal subscriber class for receiving channel messages.
    Handles buffering and flow control.
    """

    __buffer_size__: int  # Maximum buffer size
    __buffer__: list[_T]  # Message buffer
    __chanel__: Channel[_T]  # Parent channel
    __closed__: bool  # Subscriber closed state
    __read_lock__: asyncio.Event  # Lock for reading from buffer
    __write_lock__: asyncio.Event  # Lock for writing to buffer

    def __init__(self, chanel: "Channel[_T]", buffer_size: int) -> None:
        """Initialize subscriber with channel and buffer size."""
        super().__init__()
        self.__buffer_size__ = buffer_size
        self.__buffer__ = []
        self.__chanel__ = chanel
        self.__closed__ = False
        self.__read_lock__ = asyncio.Event()
        self.__write_lock__ = asyncio.Event()
        self.__write_lock__.set()

    def __aiter__(self) -> Self:
        """Make subscriber iterable."""
        return self

    async def __on_channel_state_change__(self, state: ChannelState) -> None:
        """Handle channel state changes."""
        if state == ChannelState.closed:
            await self.close()

    async def __anext__(self) -> _T:
        """Get next item when iterating."""
        try:
            return await self.read()
        except ChannelClosedError as err:
            raise StopAsyncIteration() from err

    async def __aenter__(self) -> Self:
        """Context manager entry."""
        return self

    async def __aexit__(
        self, et: type[Exception], exc: Exception, tb: Traceback
    ) -> None:
        """Context manager exit with cleanup."""
        await self.close()
        if exc and et != ChannelClosedError:
            raise exc

    async def close(self) -> None:
        """Close subscriber and cleanup resources."""
        if not self.__closed__:
            self.__closed__ = True
            await self.__chanel__.__disconnect_subscriber__(self)
            self.__read_lock__.set()
            self.__write_lock__.set()

    async def read(self) -> _T:
        """Read next message from buffer."""
        while not self.__read_lock__.is_set():
            await self.__read_lock__.wait()

        if self.__closed__ and len(self.__buffer__) == 0:
            raise ChannelClosedError()

        if len(self.__buffer__) == 1 and not self.__closed__:
            self.__read_lock__.clear()

        self.__write_lock__.set()
        return self.__buffer__.pop(0)

    async def __send__(self, data: _T) -> None:
        """Handle incoming message from publisher."""
        while not self.__write_lock__.is_set():
            await self.__write_lock__.wait()

        if self.__closed__:
            raise ChannelClosedError()

        self.__buffer__.append(data)

        if (
            self.__buffer_size__ > 0
            and len(self.__buffer__) >= self.__buffer_size__
            and not self.__closed__
        ):
            self.__write_lock__.clear()

        self.__read_lock__.set()


class _ChannelPublisher(Generic[_T]):
    """
    Internal publisher class for sending messages to channel.
    """

    __chanel__: Channel[_T]  # Parent channel
    __closed__: bool  # Publisher closed state

    def __init__(self, chanel: Channel[_T]) -> None:
        """Initialize publisher with channel."""
        super().__init__()
        self.__chanel__ = chanel
        self.__closed__ = False

    async def __on_channel_state_change__(self, state: ChannelState) -> None:
        """Handle channel state changes."""
        if state == ChannelState.closed:
            await self.close()

    async def __aenter__(self) -> Self:
        """Context manager entry."""
        return self

    async def __aexit__(
        self, et: type[Exception], exc: Exception, tb: Traceback
    ) -> None:
        """Context manager exit with cleanup."""
        await self.close()
        if exc and et != ChannelClosedError:
            raise exc

    async def close(self) -> None:
        """Close publisher and cleanup resources."""
        if not self.__closed__:
            self.__closed__ = True
            await self.__chanel__.__disconnect_publisher__(self)

    async def send(self, data: _T) -> None:
        """Send message to channel subscribers."""
        if self.__closed__:
            raise ChannelClosedError()

        await self.__chanel__.__send__(data)
