import asyncio

import aioservicekit
from aioservicekit import Service


async def timeout(service: Service, timeout: int):
    await asyncio.sleep(timeout)
    await service.stop()


class TimeoutExampleService(Service):
    """Simple service. Stopped on stop() call or shutdown event or after 10 seconds"""

    def __on_start__(self):
        # Run timeout as backgroud task
        self.create_task(timeout(self, 10))

    async def __work__(self):
        i = 0
        while self.is_running:
            await asyncio.sleep(1)
            print(f"Timeout service works {i + 1} sec.")
            i += 1


@aioservicekit.main
async def main():
    service = TimeoutExampleService()
    await service.start()
    await service.wait()


if __name__ == "__main__":
    asyncio.run(main())
