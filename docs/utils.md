# Utilities

`aioservicekit.utils` provides high-level helper functions and decorators to simplify common patterns in asynchronous applications, particularly those involving services.

## `run_services`

`run_services` is an asynchronous context manager designed to manage the lifecycle of one or more `Service` (or `Task`) instances.

```python
from contextlib import asynccontextmanager
from typing import List, AsyncGenerator, Awaitable, Any
from aioservicekit import Service, run_services

@asynccontextmanager
async def run_services(
    services: List[Service],
) -> AsyncGenerator[Awaitable[None], Any]:
    # ... implementation ...
```

**Purpose:**

*   Simplifies starting and stopping multiple services correctly.
*   Ensures services are stopped even if errors occur during startup or within the `async with` block.
*   Provides a way to wait for services to complete their natural execution.

**How it Works:**

1.  **Enter (`__aenter__`)**:
    *   Iterates through the provided `services` list.
    *   Calls `await service.start()` on each one sequentially.
    *   Keeps track of services that were successfully started.
    *   If any `start()` call raises an exception, it immediately proceeds to the `finally` block to stop all services that *were* successfully started before re-raising the startup exception.
    *   Collects the `service.wait()` awaitables for all successfully started services.
    *   `yields` an `asyncio.gather()` awaitable that combines all the `service.wait()` calls.

2.  **Inside the `with` block**:
    *   The user code executes.
    *   The `yielded` awaitable can be awaited (`await waiter`). This will block until *all* the managed services reach the `STOPED` state (either by completing their work, being stopped externally, or via shutdown signals).

3.  **Exit (`__aexit__`)**:
    *   Triggered when the `with` block finishes (normally or via an exception).
    *   Iterates through the successfully started services *in reverse order*.
    *   Calls `await service.stop()` on each one. Errors during `stop()` are caught and logged (to ensure subsequent services are still stopped), but not suppressed.
    *   The original exception (if any) that caused the exit is re-raised after cleanup.

**Example:**

```python
import asyncio
import logging
from aioservicekit import service, task, run_services, main

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

@service(name="MainWorker")
async def main_worker():
    logging.info("MainWorker running...")
    await asyncio.sleep(2)

@task(interval=1.0, name="Heartbeat")
async def heartbeat_task():
    logging.info("Heartbeat task alive.")

@main
async def app():
    svc1 = main_worker()
    tsk1 = heartbeat_task()

    logging.info("Starting services using run_services...")
    try:
        async with run_services([svc1, tsk1]) as waiter:
            logging.info("Services started. Waiting for completion or Ctrl+C.")
            # Wait until services stop (e.g., via Ctrl+C handled by Service internally)
            await waiter
        logging.info("run_services block finished normally.")
    except Exception as e:
        logging.exception("Exception occurred outside run_services block or during startup.")
    finally:
        # Services are guaranteed to have had stop() called here
        logging.info("Application exiting.")


if __name__ == "__main__":
    try:
        asyncio.run(app())
    except KeyboardInterrupt:
        logging.info("Shutdown requested.")
```

## `main`

`@main` is a decorator for your primary `async def main()` application entry point function.

```python
from typing import Callable, ParamSpec, Coroutine, Any, TypeVar
from aioservicekit import main

_P = ParamSpec("_P")
_T = TypeVar("_T")

def main(
    fn: Callable[_P, Coroutine[Any, Any, _T]],
) -> Callable[_P, Coroutine[Any, Any, _T]]:
    # ... implementation ...
```

**Purpose:**

Ensures that your application doesn't exit prematurely while background `asyncio.Task`s (which might have been created anywhere in your code, not necessarily managed by `Service` or `TaskGroup`) are still running.

**How it Works:**

1.  Calls and awaits the decorated `async def main()` function (`fn`).
2.  Gets the result from `fn`.
3.  Gets a set of *all* tasks currently known to the asyncio event loop (`asyncio.all_tasks()`).
4.  Removes the task corresponding to the `@main` wrapper itself from this set.
5.  If any other tasks remain, it calls `await asyncio.wait()` on them. This waits for these background tasks to complete.
6.  Returns the original result from `fn`.

**Why Use It?**

Without `@main`, if your `async def main()` function finishes but some background tasks (like logging queues, monitoring pings, or even tasks started by libraries you use) are still running, `asyncio.run()` might exit, potentially cancelling those tasks abruptly or leading to resource leaks or incomplete operations. `@main` provides a safety net for a cleaner shutdown.

**Example:**

```python
import asyncio
import logging
from aioservicekit import main

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def background_logger():
    logging.info("[BG Task] Starting background logger...")
    await asyncio.sleep(2) # Simulate work
    logging.info("[BG Task] Background logger finished.")

@main # Apply the decorator
async def app_main():
    logging.info("app_main started.")
    # Create a background task without any explicit management
    bg_task = asyncio.create_task(background_logger())
    logging.info("app_main doing some work...")
    await asyncio.sleep(0.5)
    logging.info("app_main finished its work, returning.")
    # Normally, the app might exit here, potentially before bg_task finishes.
    # But @main will now wait for bg_task.
    return "App Result"

if __name__ == "__main__":
    result = asyncio.run(app_main())
    logging.info(f"Application finished with result: {result}")

# Expected Output:
# INFO: app_main started.
# INFO: [BG Task] Starting background logger...
# INFO: app_main doing some work...
# INFO: app_main finished its work, returning.
# <-- @main waits here -->
# <-- after ~1.5s -->
# INFO: [BG Task] Background logger finished.
# INFO: Application finished with result: App Result
```

Using `@main` in conjunction with `run_services` and well-defined `Service`/`Task` components helps create robust asynchronous applications that start, run, and shut down cleanly.
