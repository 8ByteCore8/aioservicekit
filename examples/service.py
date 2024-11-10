import asyncio
from src import AbscractService


class ExampleService(AbscractService):
    """Simple service. Stopped on stop() call or shutdown event"""

    async def __work__(self):
        i = 0
        while self.is_running:
            await asyncio.sleep(1)
            print(f"Service works {i+1} sec.")
            i += 1