import asyncio

from aioservicekit import AbstractService


async def timeout(service: AbstractService, timeout: int):
    await asyncio.sleep(timeout)
    await service.stop()


class TimeoutExampleService(AbstractService):
    """Simple service. Stopped on stop() call or shutdown event or after 10 seconds"""

    def _start_(self):
        # Run timeout as backgroud task
        self.create_task(timeout(self, 10))

    async def _work_(self):
        i = 0
        while self.is_running:
            await asyncio.sleep(1)
            print(f"Timeout service works {i + 1} sec.")
            i += 1
