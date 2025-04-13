# Periodic Tasks

`aioservicekit.Task` is a specialized type of `Service` designed specifically for running a piece of code repeatedly at a fixed interval.

## Concept

A `Task` is essentially a `Service` where the `__work__` loop is predefined to:
1. Execute a specific task logic (defined in `__task__`).
2. Sleep for a configured `interval`.
3. Repeat.

It inherits all features of a `Service`, including lifecycle management (`start`, `stop`, `wait`), dependencies, state (`ServiceState`), error handling (`on_error`), and shutdown integration.

## Defining a Task

Similar to services, you can define tasks using a decorator or by subclassing.

### 1. Using the `@task` Decorator (Recommended)

This is the most common and straightforward way. Decorate an `async` function that performs the work you want to run periodically.

```python
import asyncio
import logging
import random
from aioservicekit import task, run_services, main

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

@task(interval=5.0, name="HealthChecker") # Run every 5 seconds
async def check_external_service_health(url: str):
    """This function is called periodically by the task."""
    logging.info(f"Checking health of {url}...")
    await asyncio.sleep(random.uniform(0.1, 0.5)) # Simulate network latency
    is_healthy = random.choice([True, True, False]) # Simulate health status
    if is_healthy:
        logging.info(f"{url} is healthy.")
    else:
        logging.error(f"{url} is UNHEALTHY!")
        # You might trigger alerts or other actions here

# --- Usage ---

@main
async def app_main():
    # Create an instance by calling the decorated function
    # Arguments are passed to the underlying check_external_service_health function
    health_checker = check_external_service_health(url="http://example.com/api/health")

    async with run_services([health_checker]):
        logging.info("Health checker running. Press Ctrl+C to stop.")
        await asyncio.Future() # Keep running until stopped

if __name__ == "__main__":
    try:
        asyncio.run(app_main())
    except KeyboardInterrupt:
        logging.info("Shutdown requested.")

```

**Decorator Arguments:**

*   **`interval` (float, required)**: The number of seconds to wait *after starting* one execution before starting the next. The timing aims to start tasks `interval` seconds apart, regardless of how long the task itself takes (up to a point - if a task takes longer than the interval, the next one starts immediately after the long one finishes).
*   **`name` (Optional[str])**: Name for the underlying service. Defaults to the function name.
*   **`dependences` (Optional[Sequence[Service]])**: List of other services this task depends on.

### 2. Subclassing `Task`

For tasks requiring more complex state or methods, you can subclass `aioservicekit.Task`.

```python
import asyncio
import logging
from aioservicekit import Task

class DataArchiverTask(Task):
    def __init__(self, source_db: Service, archive_db: Service, interval: float = 3600.0):
        # Depend on the database services
        super().__init__(
            interval=interval,
            name="DataArchiver",
            dependences=[source_db, archive_db]
        )
        self.source_db = source_db
        self.archive_db = archive_db
        self.records_archived = 0

    # --- Task Logic (Required) ---
    async def __task__(self):
        """The core logic executed periodically."""
        logging.info(f"'{self.name}': Starting data archiving cycle...")
        try:
            # Use dependency methods (assuming they exist)
            data_to_archive = await self.source_db.get_old_records()
            if data_to_archive:
                archived_count = await self.archive_db.save_records(data_to_archive)
                await self.source_db.delete_records([r.id for r in data_to_archive])
                self.records_archived += archived_count
                logging.info(f"'{self.name}': Archived {archived_count} records. Total: {self.records_archived}")
            else:
                logging.info(f"'{self.name}': No records to archive this cycle.")
        except Exception as e:
            logging.exception(f"'{self.name}': Error during archiving cycle!")
            # The base Task class's __work__ method will catch this,
            # emit it via self.on_error, and then sleep for the interval.

    # Optional: Add custom methods or override Service hooks like __on_start__ / __on_stop__
    def get_stats(self):
        return {"archived_count": self.records_archived}

# --- Usage ---
# Assuming source_db_service and archive_db_service exist
# archiver = DataArchiverTask(source_db_service, archive_db_service, interval=60*60)
# Use with run_services([source_db_service, archive_db_service, archiver])
```

**Key `Task` Components:**

*   **`__init__(self, interval, *, name=None, dependences=[])`**: Initialize the task, passing the `interval`. Call `super().__init__(...)`.
*   **`async def __task__(self)` (Abstract - Must Implement)**: The core logic to be executed periodically.
*   **`interval` (Property)**: Returns the configured interval.
*   **Inherited `Service` features**: All methods and properties from `Service` are available (`start`, `stop`, `wait`, `create_task`, `on_error`, `on_state_change`, etc.).

Choose the `@task` decorator for simple, stateless periodic actions, and subclass `Task` when you need internal state, complex dependencies, or custom lifecycle logic within your periodic task.
