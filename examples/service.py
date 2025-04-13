import asyncio

import aioservicekit
from aioservicekit import Service


class ExampleService(Service):
    """Simple service. Stopped on stop() call or shutdown event"""

    async def __work__(self):
        i = 0
        while self.is_running:
            await asyncio.sleep(1)
            print(f"Service works {i + 1} sec.")
            i += 1


@aioservicekit.main
async def main():
    service = ExampleService()
    await service.start()
    await service.wait()


if __name__ == "__main__":
    asyncio.run(main())
