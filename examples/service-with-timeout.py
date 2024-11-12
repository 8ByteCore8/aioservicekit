import asyncio
from aioservicekit import AbscractService


async def timeout(service: AbscractService, timeout: int):
    await asyncio.sleep(timeout)
    await service.stop()


class TimeoutExampleService(AbscractService):
    """Simple service. Stopped on stop() call or shutdown event or after 10 seconds"""
    
    def __start__(self):
        # Run timeout as backgroud task
        self.create_task(timeout(self, 10))

    async def __work__(self):
        i = 0
        while self.is_running:
            await asyncio.sleep(1)
            print(f"Timeout service works {i+1} sec.")
            i += 1
