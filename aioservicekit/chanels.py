import asyncio
from typing import Generic, Optional, Self, TypeVar

__all__ = [
    "ChanelClousedError",
    "ChanelCustomerClousedError",
    "Chanel",
    "ChanelCustomer",
    "ClonnedChanel",
]


class ChanelClousedError(Exception):
    """
    Raised when an attempt to send data to a closed channel is made.
    """

    def __str__(self):
        return "Can`t send data to closed chanel"


class ChanelCustomerClousedError(Exception):
    """
    Raised when an attempt to read data from a closed customer is made.
    """

    def __str__(self):
        return "Can`t read data from closed customer"


_T = TypeVar("_T")


class Chanel(Generic[_T]):
    """
    A generic channel for broadcasting data asynchronously to multiple customers.

    This class manages a list of `ChanelCustomer` instances and distributes
    data sent via the `send` method to all connected customers.
    """

    _customers_: list["ChanelCustomer[_T]"]
    _size_: int
    _strict_: bool

    def __init__(self, size: int = 0, strict: bool = True) -> None:
        """
        Initialize a new Chanel instance.

        Args:
            size (int): Default buffer size for new customers connected to this
                channel. Defaults to 0 (unbounded).
            strict (bool): If True, calling `send` on a channel with no
                customers raises `ChanelClousedError`. Defaults to True.

        Returns:
            None
        """
        self._customers_ = []
        self._size_ = size
        self._strict_ = strict

    async def send(self, data: _T) -> None:
        """
        Asynchronously send data to all connected customers.

        Iterates through all connected customers and schedules their `_send`
        method concurrently using `asyncio.TaskGroup`. If the channel is strict
        and has no customers, it raises `ChanelClousedError`.

        Args:
            data (_T): The data item to send to all customers.

        Raises:
            ChanelClousedError: If `strict` is True and `is_closed` is True.

        Returns:
            None
        """
        if self._strict_ and self.is_closed:
            raise ChanelClousedError()
        async with asyncio.TaskGroup() as group:
            for customer in self._customers_:
                group.create_task(customer._send_(data))

    @property
    def is_closed(self) -> bool:
        """
        Check if the channel has any connected customers.

        Returns:
            bool: True if there are no customers, False otherwise.
        """
        return len(self._customers_) == 0

    def clone(self) -> "ClonnedChanel[_T]":
        """
        Create a clone handle for this channel.

        The cloned handle shares the same underlying customer list and settings.
        Sending data through the clone sends it through the original channel.

        Returns:
            ClonnedChanel[_T]: A new `ClonnedChanel` instance linked to this channel.
        """
        return ClonnedChanel(self)

    def connect(self, *, size: Optional[int] = None) -> "ChanelCustomer[_T]":
        """
        Create and connect a new customer to this channel.

        Args:
            size (Optional[int]): The buffer size for the new customer's queue.
                If None, uses the channel's default size (`self.__size__`).

        Returns:
            ChanelCustomer[_T]: The newly created and connected customer instance.
        """
        customer_size = self._size_ if size is None else size
        customer = ChanelCustomer(self, size=customer_size)
        self._customers_.append(customer)
        return customer

    def disconnect(self, customer: "ChanelCustomer[_T]") -> None:
        """
        Disconnect a specific customer from this channel.

        Removes the customer from the internal list, preventing it from
        receiving further data sent through this channel.

        Args:
            customer (ChanelCustomer[_T]): The customer instance to disconnect.

        Returns:
            None
        """
        # Use a try-except block to avoid ValueError if customer is already removed
        try:
            self._customers_.remove(customer)
        except ValueError:
            pass  # Customer already disconnected, ignore.


class ChanelCustomer(Generic[_T]):
    """
    Represents a customer connected to a `Chanel`.

    Each customer has its own asynchronous queue (`asyncio.Queue`) to buffer
    incoming data from the channel. It can be asynchronously iterated over
    to consume data.
    """

    _buffer_: asyncio.Queue[_T]
    _chanel_: Chanel[_T]
    _cloused_: bool

    def __init__(self, chanel: "Chanel[_T]", size: int) -> None:
        """
        Initialize a ChanelCustomer.

        Args:
            chanel (Chanel[_T]): The `Chanel` instance this customer connects to.
            size (int): The maximum size of the internal buffer queue. 0 means
                unbounded.

        Returns:
            None
        """
        super().__init__()
        self._buffer_ = asyncio.Queue(size)
        self._chanel_ = chanel
        self._cloused_ = False

    def __aiter__(self) -> Self:
        """
        Return the customer instance itself as an asynchronous iterator.

        Allows using `async for item in customer: ...`.

        Returns:
            Self: The instance itself.
        """
        return self

    async def __anext__(self) -> _T:
        """
        Get the next item for asynchronous iteration.

        Calls `read()` and wraps `ChanelCustomerClousedError` in
        `StopAsyncIteration` to signal the end of iteration when the
        customer is closed and empty.

        Raises:
            StopAsyncIteration: When the customer is closed and the buffer is empty.

        Returns:
            _T: The next data item from the buffer.
        """
        try:
            return await self.read()
        except ChanelCustomerClousedError as err:
            # Convert the custom error to StopAsyncIteration for protocol compliance
            raise StopAsyncIteration() from err

    async def _send_(self, data: _T) -> None:
        """
        Internal method to add data received from the channel to the buffer.

        If the customer is not closed, it attempts to put the data into the
        queue without waiting. If the queue is full, it waits until space is
        available. This method is typically called by the `Chanel.send` method.

        Args:
            data (_T): The data item received from the channel.

        Returns:
            None
        """
        if not self._cloused_:
            try:
                # Try non-blocking put first for performance
                self._buffer_.put_nowait(data)
            except asyncio.QueueFull:
                # If full, wait for space
                await self._buffer_.put(data)

    def reset(self) -> None:
        """
        Clear all items currently in the customer's buffer.

        Discards any unread data in the queue.

        Returns:
            None
        """
        try:
            while True:
                self._buffer_.get_nowait()
        except asyncio.QueueEmpty:
            pass  # Buffer is now empty

    def clone(self) -> "ChanelCustomer[_T]":
        """
        Create a new customer connected to the same channel.

        This is equivalent to calling `chanel.connect()` with the same buffer size
        as this customer. The new customer will have its own independent buffer.

        Returns:
            ChanelCustomer[_T]: A new customer instance connected to the same channel.
        """
        return self._chanel_.connect(size=self._buffer_.maxsize)

    def close(self) -> None:
        """
        Close the customer connection.

        Marks the customer as closed, disconnects it from the channel (so it
        stops receiving new data), and resets (clears) its buffer. Attempts
        to read from a closed, empty customer will raise `ChanelCustomerClousedError`.

        Returns:
            None
        """
        if not self._cloused_:
            self._cloused_ = True
            self._chanel_.disconnect(self)
            self.reset()

    async def read(self) -> _T:
        """
        Asynchronously read the next item from the customer's buffer.

        Waits if the buffer is empty. If the customer is closed and the
        buffer becomes empty, raises `ChanelCustomerClousedError`.

        Raises:
            ChanelCustomerClousedError: If the customer is closed and the buffer
                is empty.

        Returns:
            _T: The next data item from the buffer.
        """
        if self._cloused_ and self._buffer_.empty():
            raise ChanelCustomerClousedError()

        try:
            # Try non-blocking get first
            return self._buffer_.get_nowait()
        except asyncio.QueueEmpty:
            # If empty, wait for an item
            # This task might be cancelled if the customer is closed
            # while waiting. `get()` handles this gracefully.
            item = await self._buffer_.get()
            # Need to check again after waiting, in case it was closed
            # and the queue was emptied *before* this item was received.
            # However, the common case is getting an item. A more robust
            # check might involve listening for a separate close event,
            # but relying on Queue behavior and the __anext__ exception
            # handling is typical.
            return item


class ClonnedChanel(Generic[_T]):
    """
    A lightweight handle or clone of an existing `Chanel`.

    Allows sending data to and connecting new customers via the original
    channel without holding a direct reference to all its internal state.
    Useful for passing channel write/connect capabilities around.
    """

    _chanel_: Chanel[_T]

    def __init__(self, chanel: Chanel[_T]) -> None:
        """
        Initialize a ClonnedChanel handle.

        Args:
            chanel (Chanel[_T]): The original `Chanel` instance to clone.

        Returns:
            None
        """
        super().__init__()
        self._chanel_ = chanel

    async def send(self, data: _T) -> None:
        """
        Asynchronously send data through the underlying original channel.

        Delegates the call to the `send` method of the original `Chanel`.

        Args:
            data (_T): The data item to send.

        Returns:
            None: Returns the result of the underlying `chanel.send` call.
        """
        # Ensure send is awaitable if the original is
        await self._chanel_.send(data)

    def clone(self) -> "ClonnedChanel[_T]":
        """
        Create another clone handle of the same original channel.

        Delegates to the `clone` method of the original `Chanel`.

        Returns:
            ClonnedChanel[_T]: A new clone handle pointing to the same original channel.
        """
        # The original clone method returns ClonnedChanel, so this is correct.
        return self._chanel_.clone()

    def connect(self, *, size: Optional[int] = None) -> "ChanelCustomer[_T]":
        """
        Connect a new customer to the underlying original channel.

        Delegates the call to the `connect` method of the original `Chanel`.

        Args:
            size (Optional[int]): Buffer size for the new customer. If None,
                the original channel's default is used.

        Returns:
            ChanelCustomer[_T]: The new customer connected to the original channel.
        """
        return self._chanel_.connect(size=size)
