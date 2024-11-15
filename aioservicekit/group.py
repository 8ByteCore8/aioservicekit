import asyncio
from typing import Awaitable, Set


class TaskGroup:
    __tasks: Set[asyncio.Task]
    __uncanceliable_tasks: Set[asyncio.Task]

    def __init__(self):
        self.__tasks = set()
        self.__uncanceliable_tasks = set()

    def create_task(self, coro: Awaitable, canceliable: bool = True):
        task = asyncio.create_task(coro)

        if canceliable:
            self.__tasks.add(task)
            task.add_done_callback(lambda *args, **kwargs: self.__tasks.remove(task))
        else:
            self.__uncanceliable_tasks.add(task)
            task.add_done_callback(
                lambda *args, **kwargs: self.__uncanceliable_tasks.remove(task)
            )

        return task

    def cancel(self):
        """Cancel task in group"""
        for task in self.__tasks:
            task.cancel()

    async def wait(self):
        if len(self.__tasks) == len(self.__uncanceliable_tasks) == 0:
            return

        while True:
            try:
                _, pending = await asyncio.wait(*self.__tasks)
                if len(pending) == 0:
                    break
            except asyncio.CancelledError:
                # Ignore cancelation
                pass

        await asyncio.wait(*self.__uncanceliable_tasks)
