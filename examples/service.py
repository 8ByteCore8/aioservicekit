import asyncio

from aioservicekit import AbstractService


class ExampleService(AbstractService):
    """Simple service. Stopped on stop() call or shutdown event"""

    async def _work_(self):
        i = 0
        while self.is_running:
            await asyncio.sleep(1)
            print(f"Service works {i + 1} sec.")
            i += 1
