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
    def __str__(self):
        return "Can`t send data to closed chanel"


class ChanelCustomerClousedError(Exception):
    def __str__(self):
        return "Can`t read data from closed customer"


_T = TypeVar("_T")


class Chanel(Generic[_T]):
    __customers__: list["ChanelCustomer[_T]"]
    __size__: int
    __strict__: bool

    async def send(self, data: _T):
        if self.__strict__ and self.is_closed:
            raise ChanelClousedError()
        async with asyncio.TaskGroup() as group:
            for customer in self.__customers__:
                group.create_task(customer._send(data))

    def __init__(self, size: int = 0, strict: bool = True):
        self.__customers__ = []
        self.__size__ = size
        self.__strict__ = strict

    @property
    def is_closed(self):
        return len(self.__customers__) == 0

    def clone(self) -> "ClonnedChanel[_T]":
        return ClonnedChanel(self)

    def connect(self, *, size: Optional[int] = None) -> "ChanelCustomer[_T]":
        customer = ChanelCustomer(self, size=self.__size__ if size is None else size)
        self.__customers__.append(customer)
        return customer

    def disconnect(self, customer: "ChanelCustomer[_T]"):
        self.__customers__.remove(customer)


class ChanelCustomer(Generic[_T]):
    __buffer__: asyncio.Queue
    __chanel__: Chanel[_T]
    __cloused__: bool

    def __init__(self, chanel: "Chanel[_T]", size: int):
        super().__init__()
        self.__buffer__ = asyncio.Queue(size)
        self.__chanel__ = chanel
        self.__cloused__ = False

    async def _send(self, data: _T) -> None:
        if not self.__cloused__:
            try:
                self.__buffer__.put_nowait(data)
            except asyncio.QueueFull:
                await self.__buffer__.put(data)

    def reset(self):
        try:
            while True:
                self.__buffer__.get_nowait()
        except asyncio.QueueEmpty:
            pass

    def clone(self):
        return self.__chanel__.connect(size=self.__buffer__.maxsize)

    def close(self):
        self.__cloused__ = True
        self.__chanel__.disconnect(self)
        self.reset()

    def __aiter__(self) -> Self:
        return self

    async def read(self) -> _T:
        if self.__cloused__ and self.__buffer__.empty():
            raise ChanelCustomerClousedError()

        try:
            return self.__buffer__.get_nowait()
        except asyncio.QueueEmpty:
            return await self.__buffer__.get()

    async def __anext__(self) -> _T:
        try:
            return await self.read()
        except ChanelCustomerClousedError as err:
            raise StopAsyncIteration() from err


class ClonnedChanel(Generic[_T]):
    __chanel__: Chanel[_T]

    def __init__(self, chanel: Chanel[_T]):
        super().__init__()
        self.__chanel__ = chanel

    def send(self, data: _T):
        return self.__chanel__.send(data)

    def clone(self) -> "ClonnedChanel[_T]":
        return self.__chanel__.clone()

    def connect(self, *, size: Optional[int] = None) -> "ChanelCustomer[_T]":
        return self.__chanel__.connect(size=size)
