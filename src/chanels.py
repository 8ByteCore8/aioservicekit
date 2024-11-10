import asyncio
from typing import Any, Coroutine, Generic, TypeVar

_T = TypeVar("T")


class Chanel(Generic[_T]):
    __buffer: asyncio.Queue

    def __init__(self, size: int = 0):
        super().__init__()
        self.__buffer = asyncio.Queue(size)

    def send(self, data: _T) -> Coroutine[Any, Any, None]:
        return self.__buffer.put(data)

    def recive(self) -> Coroutine[Any, Any, _T]:
        return self.__buffer.get()
