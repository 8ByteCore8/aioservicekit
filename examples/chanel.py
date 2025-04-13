import asyncio

import aioservicekit
from aioservicekit import Service, Chanel
from aioservicekit.chanels import ChanelCustomer


async def timeout(service: Service, timeout: int):
    await asyncio.sleep(timeout)
    await service.stop()


NUMBERS: Chanel[tuple[str, int]] = Chanel()


@aioservicekit.service()
async def Generator(name: str, limit: int):
    for i in range(limit):
        await NUMBERS.send((name, i))
        await asyncio.sleep(1)
    raise asyncio.CancelledError()


class Printer(Service):
    __receiver__: ChanelCustomer[tuple[str, int]]

    def __on_start__(self) -> None:
        self.__receiver__ = NUMBERS.connect()

    def __on_stop__(self) -> None:
        NUMBERS.disconnect(self.__receiver__)

    async def __work__(self):
        async for name, num in self.__receiver__:
            print(f"Printer receive {num} from Generator {name}.")


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
