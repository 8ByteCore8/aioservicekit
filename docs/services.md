# Services

The `Service` class is the cornerstone of `aioservicekit` for building long-running, managed asynchronous components.

## Concept

A `Service` represents a unit of work that has a distinct lifecycle (`STARTING`, `RUNNING`, `STOPING`, `STOPED`). It typically runs a main loop (`__work__`) and can manage background tasks. Services handle their own startup, shutdown, and dependency management.

## Defining a Service

There are two main ways to define a service:

### 1. Using the `@service` Decorator (Recommended for simple cases)

This is the easiest way, shown in the [Getting Started](./getting_started.md) guide. You decorate an `async` function that contains the logic for one iteration of your service's work.

```python
import asyncio
import logging
from aioservicekit import service

@service(name="MyWorkerService")
async def my_work_loop(config_param: str):
  """This function is called repeatedly by the service."""
  logging.info(f"Doing work with config: {config_param}")
  await asyncio.sleep(2)
  logging.info("Work cycle complete.")

# Create an instance by calling the decorated function
# Arguments passed here are passed to the underlying my_work_loop function
worker_service = my_work_loop(config_param="value1")

# Now worker_service can be started/stopped, e.g., using run_services
```

### 2. Subclassing `Service`

For more complex services requiring internal state, custom initialization, or cleanup logic, you can subclass `aioservicekit.Service`.

```python
import asyncio
import logging
from aioservicekit import Service, ServiceState

class ComplexService(Service):
    def __init__(self, api_key: str, name: str = "ComplexService"):
        super().__init__(name=name)
        self.api_key = api_key
        self._internal_data = {}
        self._connection = None # Example resource

        # Subscribe to state changes (optional)
        self.on_state_change.add_listener(self._log_state_change)

    async def _log_state_change(self, state: ServiceState):
        logging.info(f"Service '{self.name}' changed state to: {state.name}")

    # --- Lifecycle Hooks (Optional) ---

    async def __on_start__(self):
        """Called during start(), before entering RUNNING state."""
        logging.info(f"'{self.name}': Performing startup tasks...")
        # Simulate connecting to an external resource
        await asyncio.sleep(0.5)
        self._connection = {"status": "connected", "key": self.api_key[:4]}
        logging.info(f"'{self.name}': Connection established: {self._connection}")

    async def __on_stop__(self):
        """Called during stop(), after the main loop is cancelled."""
        logging.info(f"'{self.name}': Performing shutdown tasks...")
        # Simulate closing the connection
        if self._connection:
            await asyncio.sleep(0.2)
            logging.info(f"'{self.name}': Closing connection: {self._connection}")
            self._connection = None
        logging.info(f"'{self.name}': Cleanup complete.")

    # --- Main Work Loop (Required) ---

    async def __work__(self):
        """The core logic, called repeatedly while RUNNING."""
        logging.info(f"'{self.name}': Processing data...")
        # Example: Use the connection, update internal state
        if self._connection:
            self._internal_data["last_check"] = asyncio.get_event_loop().time()
            await asyncio.sleep(3) # Simulate work
            logging.info(f"'{self.name}': Processing finished.")
        else:
            logging.warning(f"'{self.name}': No connection available, skipping work.")
            # Maybe try to reconnect or stop the service?
            # await self.stop() # Example: stop service if connection lost
            await asyncio.sleep(5) # Wait longer if connection is down

    # --- Custom Methods (Optional) ---
    def get_status(self) -> dict:
        return {
            "state": self.state.name,
            "connection": self._connection,
            "internal_data": self._internal_data,
        }

# --- Usage ---
# complex_service = ComplexService(api_key="secret-key-123")
# Use with run_services or manage manually:
# await complex_service.start()
# await complex_service.wait() # Waits until STOPED
```

**Key `Service` Components:**

*   **`__init__(self, *, name=None, dependences=[])`**: Initialize your service. Call `super().__init__(...)`.
*   **`async def __work__(self)` (Abstract - Must Implement)**: The core logic loop. Called repeatedly while the service is `RUNNING`. If this method finishes or raises an unhandled exception (after being emitted to `on_error`), the service will initiate a stop. It *should* contain `await` calls (e.g., `asyncio.sleep`, I/O operations) to yield control.
*   **`async def __on_start__(self)` (Optional)**: Hook executed during `start()` *after* dependencies are running but *before* `__work__` starts and the state becomes `RUNNING`. Use for async initialization.
*   **`async def __on_stop__(self)` (Optional)**: Hook executed during `stop()` *after* `__work__` is cancelled and *after* background tasks are awaited. Use for async cleanup.
*   **`async def start(self)`**: Transitions state `STOPED` -> `STARTING` -> `RUNNING`. Waits for dependencies, runs `__on_start__`, starts the `__work__` loop task, subscribes to `on_shutdown`. Idempotent if already started/running.
*   **`async def stop(self)`**: Transitions state `RUNNING`/`STARTING` -> `STOPING` -> `STOPED`. Cancels `__work__`, runs `__on_stop__`, cancels background tasks, unsubscribes from `on_shutdown`, waits for cleanup. Idempotent if already stopping/stopped.
*   **`async def wait(self)`**: Returns an awaitable that completes only when the service reaches the `STOPED` state.
*   **`async def restart(self)`**: Convenience method: `await self.stop()` then `await self.wait()` then `await self.start()`.
*   **`create_task(self, coro, *, name=None, context=None, canceliable=True)`**: Creates an `asyncio.Task` managed by the service's internal `TaskGroup`. These tasks are automatically cancelled during `stop()` if `canceliable` is `True`. Errors are emitted via `self.on_error`.
*   **`state` (Property)**: Returns the current `ServiceState`.
*   **`is_running`, `is_stoped` (Properties)**: Boolean checks for state.
*   **`name` (Property)**: The service name.
*   **`on_state_change` (Event)**: An `Event[ServiceState]` triggered when the state changes.
*   **`on_error` (Event)**: An `Event[BaseException]` triggered when an unhandled exception occurs in `__work__` or any background task created with `create_task`.

## Dependencies

Services can depend on other services. This ensures that a service only starts after its dependencies are running and stops if any of its dependencies stop.

```python
# Assuming 'database_service' is another Service instance
@service(name="ApiService", dependences=[database_service])
async def api_service_worker():
    # This code will only run when database_service is RUNNING
    data = await database_service.query("SELECT * FROM users")
    # ... process data ...
    await asyncio.sleep(5)

# When using run_services, dependencies are handled automatically:
# async with run_services([database_service, api_service_worker()]):
#    ...
```

*   Dependencies are passed as a list to the `__init__` method (or the `@service` decorator).
*   `start()` will wait for all dependencies to reach the `RUNNING` state.
*   If any dependency transitions to `STOPING` or `STOPED`, the dependent service will automatically call its own `stop()` method.

Services provide a powerful abstraction for managing the lifecycle and execution of asynchronous components within your application. Choose the decorator for simplicity or subclassing for more control.
