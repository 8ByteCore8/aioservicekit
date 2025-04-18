import asyncio

import aioservicekit
from aioservicekit import Channel, Service

NUMBERS: Channel[tuple[str, int]] = Channel()


@aioservicekit.services()
async def Generator(name: str, limit: int):
    async with await NUMBERS.connect() as pub:
        for i in range(limit):
            await pub.send((name, i))
            await asyncio.sleep(1)

    raise asyncio.CancelledError()


class Printer(Service):
    async def __work__(self):
        async with await NUMBERS.subscribe() as sub:
            async for name, num in sub:
                print(f"Printer receive {num} from Generator {name}.")
        raise asyncio.CancelledError()


@aioservicekit.main
async def main():
    services: list[Service] = [
        gen := Generator("G1", 10),
        Printer(dependences=[gen]),
    ]

    async with aioservicekit.run_services(services) as waiter:
        await waiter


if __name__ == "__main__":
    asyncio.run(main())
