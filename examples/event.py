import asyncio

from aioservicekit import Event


def create_callback(id: int):
    async def callback(num: int):
        print(f"Listener {id}: {num}")

    return callback


async def main():
    on_example = Event[int]()

    for i in range(3):
        on_example.add_listener(create_callback(i))

    for i in range(10):
        await asyncio.sleep(1)
        await on_example.emit(i)
