import asyncio
from collections.abc import Coroutine
from inspect import isawaitable
from typing import Any, Generic, Optional, Self, TypeVar

__all__ = [
    "ChanelCustomerClousedError",
    "Chanel",
    "ChanelCustomer",
    "ClonnedChanel",
]


class ChanelCustomerClousedError(Exception):
    """
    Raised when an attempt to read data from a closed customer is made.

    This typically happens during asynchronous iteration (`async for`) or
    direct calls to `read()` after the customer has been closed and its
    internal buffer is empty.
    """

    def __str__(self):
        """Return a human-readable error message."""
        return "Can`t read data from closed customer"


_T = TypeVar("_T")


class Chanel(Generic[_T]):
    """
    A generic channel for broadcasting data asynchronously to multiple customers.

    This class acts as a central hub. Data sent to the `Chanel` using the
    `send` method is distributed concurrently to all currently connected
    `ChanelCustomer` instances. Each customer manages its own buffer.
    """

    __customers__: set["ChanelCustomer[_T]"]
    __size__: int
    __open_waiter__: asyncio.Event

    def __init__(self, size: int = 0) -> None:
        """
        Initialize a new Chanel instance.

        Args:
            size (int): Default buffer size for new customers connected to this
                channel. A size of 0 means the buffer is unbounded. Defaults to 0.

        Returns:
            None
        """
        self.__customers__ = set()
        self.__size__ = size
        self.__open_waiter__ = asyncio.Event()

    # Properties
    @property
    def is_closed(self) -> bool:
        """
        Check if the channel has no connected customers.

        Returns:
            bool: True if there are no customers connected, False otherwise.
                  Equivalent to `not self.is_opened`.
        """
        return not self.is_opened

    @property
    def is_opened(self) -> bool:
        """
        Check if the channel has at least one connected customer.

        Returns:
            bool: True if there is at least one customer, False otherwise.
                  Indicates if messages sent will be received by at least one customer.
        """
        return self.__open_waiter__.is_set()

    # Public Methods
    async def send(self, data: _T) -> None:
        """
        Asynchronously send data to all connected customers.

        If the channel currently has no customers (`is_closed` is True), this
        method will wait until at least one customer connects before sending
        the data.

        Once open, it iterates through all connected `ChanelCustomer` instances.
        Sending to a customer might block if its buffer is full; these waits
        are managed concurrently using `asyncio.TaskGroup`.

        Args:
            data (_T): The data item to broadcast to all customers.

        Returns:
            None
        """
        if self.is_closed:
            # Wait until a customer connects if the channel is currently closed.
            await self.__open_waiter__.wait()

        # Use TaskGroup to send concurrently to all customers.
        async with asyncio.TaskGroup() as group:
            for customer in self.__customers__:
                # Internal send might return a coroutine if the customer buffer is full.
                if isawaitable(res := customer.__send__(data)):
                    group.create_task(res)  # Schedule the wait if needed.

    def clone(self) -> "ClonnedChanel[_T]":
        """
        Create a lightweight clone (handle) for this channel.

        The cloned handle (`ClonnedChanel`) allows sending data and connecting
        new customers via the original channel without needing a direct reference
        to the original `Chanel` object itself. Useful for passing write/connect
        capabilities.

        Returns:
            ClonnedChanel[_T]: A new `ClonnedChanel` instance linked to this channel.
        """
        return ClonnedChanel(self)

    def connect(self, *, size: Optional[int] = None) -> "ChanelCustomer[_T]":
        """
        Create and connect a new customer to this channel.

        Instantiates a `ChanelCustomer`, adds it to the set of customers,
        and ensures the channel is marked as open.

        Args:
            size (Optional[int]): The buffer size for the new customer's queue.
                If None, the channel's default size is used.
                A size of 0 means unbounded.

        Returns:
            ChanelCustomer[_T]: The newly created and connected customer instance.
        """
        customer_size = self.__size__ if size is None else size
        customer = ChanelCustomer(self, size=customer_size)

        self.__customers__.add(customer)
        # Ensure the channel is marked as open now that there's a customer.
        self.__open_waiter__.set()

        return customer

    def disconnect(self, customer: "ChanelCustomer[_T]") -> None:
        """
        Disconnect a specific customer from this channel.

        Removes the customer from the list, preventing it from
        receiving further data sent through this channel. It also calls the
        customer's `close` method. If this was the last customer, the
        channel is marked as closed.

        Args:
            customer (ChanelCustomer[_T]): The customer instance to disconnect.

        Returns:
            None
        """
        self.__customers__.discard(customer)
        # Ensure the customer itself is properly closed.
        customer.close()
        # If no customers remain, mark the channel as closed.
        if len(self.__customers__) == 0:
            self.__open_waiter__.clear()


class ChanelCustomer(Generic[_T]):
    """
    Represents a customer connected to a `Chanel`, acting as a consumer endpoint.

    Each customer maintains its own internal buffer of data
    received from the `Chanel`. It supports asynchronous iteration (`async for`)
    for consuming data sequentially.
    """

    __buffer__: asyncio.Queue[_T]
    __chanel__: Chanel[_T]
    __cloused__: bool

    def __init__(self, chanel: "Chanel[_T]", size: int) -> None:
        """
        Initialize a ChanelCustomer. Typically called by `Chanel.connect`.

        Args:
            chanel (Chanel[_T]): The `Chanel` instance this customer belongs to.
            size (int): The maximum size of the internal buffer queue. 0 means
                unbounded.

        Returns:
            None
        """
        super().__init__()
        self.__buffer__ = asyncio.Queue(size)
        self.__chanel__ = chanel
        self.__cloused__ = False

    # Dunder Methods
    def __aiter__(self) -> Self:
        """
        Return the customer instance itself as an asynchronous iterator.

        This enables the use of the customer in an `async for` loop:
        `async for item in customer: ...`

        Returns:
            Self: The customer instance itself.
        """
        return self

    async def __anext__(self) -> _T:
        """
        Asynchronously get the next item for iteration.

        This method is called implicitly by `async for` loops. It attempts
        to `read()` the next item from the buffer. If the customer is closed
        and the buffer is empty (`read()` raises `ChanelCustomerClousedError`),
        it translates this into `StopAsyncIteration` to correctly signal the
        end of the asynchronous iteration.

        Raises:
            StopAsyncIteration: If the customer is closed and its buffer is empty.

        Returns:
            _T: The next data item from the buffer.
        """
        try:
            # Delegate to the read() method for the core logic.
            return await self.read()
        except ChanelCustomerClousedError as err:
            # Convert the custom error to StopAsyncIteration for protocol compliance.
            raise StopAsyncIteration() from err

    # Public Methods
    def reset(self) -> None:
        """
        Clear all items currently waiting in the customer's buffer.

        Returns:
            None
        """
        try:
            # Consume items until the queue is empty.
            while True:
                self.__buffer__.get_nowait()
        except asyncio.QueueEmpty:
            pass  # Buffer is now empty

    def clone(self) -> "ChanelCustomer[_T]":
        """
        Create a new, independent customer connected to the same `Chanel`.

        This is a convenience method equivalent to calling `chanel.connect()`
        on the underlying channel, using the same buffer size as this customer.
        The new customer will start with an empty buffer and receive subsequent
        data broadcast by the channel independently.

        Returns:
            ChanelCustomer[_T]: A new customer instance connected to the same channel.
        """
        # Delegate to the channel's connect method with the current buffer size.
        return self.__chanel__.connect(size=self.__buffer__.maxsize)

    def close(self) -> None:
        """
        Close the customer connection gracefully.

        Marks the customer as closed, preventing it from receiving new data.
        Calls `disconnect` on the parent `Chanel` to remove this customer
        from future broadcasts.
        Calls `reset` to clear any remaining items in the buffer.

        Once closed, subsequent calls to `read()` or `__anext__()` (when the
        buffer is empty) will raise `ChanelCustomerClousedError` or
        `StopAsyncIteration`, respectively.

        Returns:
            None
        """
        if not self.__cloused__:
            self.__cloused__ = True
            # Request disconnection from the channel.
            self.__chanel__.disconnect(self)
            # Clear any remaining buffered items.
            self.reset()

    async def read(self) -> _T:
        """
        Asynchronously read the next available item from the customer's buffer.

        Waits if the buffer is currently empty until an item becomes available.
        If the customer has been closed and the buffer is empty, it immediately
        raises `ChanelCustomerClousedError`.

        Raises:
            ChanelCustomerClousedError: If the customer is closed and the buffer
                is empty when the read attempt is made or completes.

        Returns:
            _T: The next data item from the buffer.
        """
        # Check if closed and empty *before* potentially waiting.
        if self.__cloused__ and self.__buffer__.empty():
            raise ChanelCustomerClousedError()

        try:
            # Try non-blocking get first for efficiency if an item is ready.
            return self.__buffer__.get_nowait()
        except asyncio.QueueEmpty:
            # If empty, wait for an item to arrive.
            # `get()` will wait indefinitely until an item is put or the task
            # waiting on it is cancelled.
            item = await self.__buffer__.get()
            self.__buffer__.task_done()  # Notify queue the item is processed
            return item
        # No need for a final check here, as __anext__ handles the StopAsyncIteration

    # Internal Methods (used by Chanel)
    def __send__(self, data: _T) -> Coroutine[Any, Any, None] | None:
        """
        Internal method used by `Chanel` to deliver data to this customer.

        If the customer is not closed, it attempts to put the received data
        into the customer's buffer queue. It first tries a non-blocking put.
        If the queue is full (only possible for bounded queues), it returns
        the awaitable coroutine, which the `Chanel.send` method will schedule
        to wait for space. If the customer is closed, this method does nothing.

        Args:
            data (_T): The data item received from the channel.

        Returns:
            Optional[Coroutine[Any, Any, None]]: Returns `None` if the item was
            added immediately or if the customer is closed. Returns an awaitable
            `put` coroutine if the buffer is full and needs to wait for space.
        """
        if not self.__cloused__:
            try:
                # Try non-blocking put first for performance.
                self.__buffer__.put_nowait(data)
                return None  # Indicate immediate success
            except asyncio.QueueFull:
                # If full, return the awaitable put operation.
                return self.__buffer__.put(data)
        return None  # Customer is closed, return None


class ClonnedChanel(Generic[_T]):
    """
    A lightweight handle or clone of an existing `Chanel`.

    This class acts as a proxy to an underlying `Chanel` instance. It allows
    sending data to the channel (`send`) and creating new customers (`connect`)
    without exposing the full `Chanel` object or its internal customer list.

    Useful for scenarios where only the ability to send or connect is needed,
    promoting encapsulation.
    """

    __chanel__: Chanel[_T]

    def __init__(self, chanel: Chanel[_T]) -> None:
        """
        Initialize a ClonnedChanel handle.

        Args:
            chanel (Chanel[_T]): The original `Chanel` instance to wrap.

        Returns:
            None
        """
        super().__init__()
        self.__chanel__ = chanel

    # Public Methods
    async def send(self, data: _T) -> None:
        """
        Asynchronously send data through the underlying original channel.

        Delegates the call directly to the `send` method of the original `Chanel`.

        Args:
            data (_T): The data item to send.

        Returns:
            None
        """
        # Delegate the send operation to the actual channel.
        await self.__chanel__.send(data)

    def clone(self) -> "ClonnedChanel[_T]":
        """
        Create another clone handle of the same original channel.

        Delegates to the `clone` method of the underlying `Chanel`, effectively
        creating another lightweight handle pointing to the same original channel.

        Returns:
            ClonnedChanel[_T]: A new clone handle.
        """
        # Delegate cloning to the actual channel.
        return self.__chanel__.clone()

    def connect(self, *, size: Optional[int] = None) -> "ChanelCustomer[_T]":
        """
        Connect a new customer to the underlying original channel.

        Delegates the call directly to the `connect` method of the original `Chanel`.

        Args:
            size (Optional[int]): Buffer size for the new customer. If None,
                the original channel's default size is used.

        Returns:
            ChanelCustomer[_T]: The new customer connected to the original channel.
        """
        # Delegate connection to the actual channel.
        return self.__chanel__.connect(size=size)
