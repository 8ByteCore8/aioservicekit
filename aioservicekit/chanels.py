import asyncio
from typing import Generic, List, Optional, Self, TypeVar


class ChanelCloused(Exception):
    def __str__(self):
        return "Can`t send data to closed chanel"


class ChanelCustomerCloused(Exception):
    def __str__(self):
        return "Can`t read data from closed customer"


_T = TypeVar("T")


class Chanel(Generic[_T]):
    __customers: List["ChanelCustomer[_T]"]
    __size: int
    __strict: bool

    async def send(self, data: _T):
        if self.__strict and self.is_closed:
            raise ChanelCloused()
        async with asyncio.TaskGroup() as group:
            for customer in self.__customers:
                group.create_task(customer._send(data))

    def __init__(self, size: int = 0, strict: bool = True):
        self.__customers = []
        self.__size = size
        self.__strict = strict

    @property
    def is_closed(self):
        return len(self.__customers) == 0

    def clone(self) -> "ClonnedChanel[_T]":
        return ClonnedChanel(self)

    def connect(self, *, size: Optional[int] = None) -> "ChanelCustomer[_T]":
        customer = ChanelCustomer(self, size=self.__size if size is None else size)
        self.__customers.append(customer)
        return customer

    def disconnect(self, customer: "ChanelCustomer[_T]"):
        self.__customers.remove(customer)


class ChanelCustomer(Generic[_T]):
    __buffer: asyncio.Queue
    __chanel: Chanel[_T]
    __cloused: bool

    def __init__(self, chanel: "Chanel[_T]", size: int):
        super().__init__()
        self.__buffer = asyncio.Queue(size)
        self.__chanel = chanel
        self.__cloused = False

    async def _send(self, data: _T) -> None:
        if not self.__cloused:
            try:
                self.__buffer.put_nowait(data)
            except asyncio.QueueFull:
                await self.__buffer.put(data)

    def reset(self):
        try:
            while True:
                self.__buffer.get_nowait()
        except asyncio.QueueEmpty:
            pass

    def clone(self):
        return self.__chanel.connect(size=self.__buffer.maxsize)

    def close(self):
        self.__cloused = True
        self.__chanel.disconnect(self)
        self.reset()

    def __aiter__(self) -> Self:
        return self

    async def read(self) -> _T:
        if self.__cloused and self.__buffer.empty():
            raise ChanelCustomerCloused()

        try:
            return self.__buffer.get_nowait()
        except asyncio.QueueEmpty:
            return await self.__buffer.get()

    async def __anext__(self) -> _T:
        try:
            return await self.read()
        except ChanelCustomerCloused as err:
            raise StopAsyncIteration() from err


class ClonnedChanel(Generic[_T]):
    __chanel: Chanel[_T]

    def __init__(self, chanel: Chanel[_T]):
        super().__init__()
        self.__chanel = chanel

    def send(self, data: _T):
        return self.__chanel.send(data)

    def clone(self) -> "ClonnedChanel[_T]":
        return self.__chanel.clone()

    def connect(self, *, size: Optional[int] = None) -> "ChanelCustomer[_T]":
        return self.__chanel.connect(size=size)
