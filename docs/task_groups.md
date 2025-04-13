# Task Groups

`aioservicekit.TaskGroup` provides a robust way to manage the concurrent execution of multiple `asyncio.Task`s, similar to Python 3.11's `asyncio.TaskGroup` but with added features for error handling and control, available also for older Python versions (using the `exceptiongroup` backport if needed).

## Concept

A `TaskGroup` is used as an asynchronous context manager (`async with`). Tasks created within the group (`group.create_task(...)`) are managed collectively. The context manager ensures that all tasks within the group are awaited upon exiting the block. It provides mechanisms to handle errors occurring within tasks and control task cancellation.

## Key Features & API

*   **Context Manager**: Used via `async with TaskGroup(...) as group:`.
*   **Task Creation**: `group.create_task(coro, *, name=None, context=None, canceliable=True) -> asyncio.Task`
    *   Creates, schedules, and manages an `asyncio.Task` for the given coroutine `coro`.
    *   **`canceliable` (bool)**: If `True` (default), the task will be cancelled if the group exits due to an unhandled exception (and `error_tolerance=False`), or if `group.cancel()` is called explicitly. If `False`, the task will *not* be cancelled in these scenarios and the `TaskGroup` will wait for it to complete naturally during `__aexit__` or `wait()`. This is useful for critical cleanup tasks that must run to completion.
*   **Error Tolerance**: `TaskGroup(*, error_tolerance: bool = False)`
    *   If `error_tolerance=False` (default): The first exception raised by any task (that isn't `asyncio.CancelledError`) will cause the `TaskGroup` to cancel all other *cancellable* tasks. Upon exiting the `async with` block (or calling `wait()`), a `BaseExceptionGroup` containing the error(s) that occurred before cancellation is raised.
    *   If `error_tolerance=True`: Exceptions in tasks do *not* cause other tasks to be cancelled. All tasks run to completion (or until cancelled externally). Any exceptions are collected and stored. They are *not* raised automatically on exit but can be accessed via the `error` property. The `on_error` event is still emitted for each error.
*   **Error Event**: `group.on_error` (`Event[BaseException]`)
    *   This event is emitted whenever a task managed by the group finishes with an exception (other than `asyncio.CancelledError`), regardless of the `error_tolerance` setting. You can add listeners to log errors or react to them immediately.
*   **Error Access**: `group.error` (Property) -> `list[BaseException]`
    *   Returns a list of exceptions collected from completed tasks. If `error_tolerance=False`, this typically contains only the first error(s) that triggered cancellation. If `error_tolerance=True`, it contains all errors from all completed tasks that failed.
*   **Waiting**: `async def wait(self)`
    *   Waits until *all* tasks (cancellable and uncancellable) in the group have completed. If `error_tolerance=False` and errors occurred, raises `BaseExceptionGroup` after waiting.
*   **Cancellation**: `cancel(self)`
    *   Explicitly cancels all *cancellable* tasks currently running in the group.

## Examples

### Basic Usage (Default Error Handling)

```python
import asyncio
import logging
from aioservicekit import TaskGroup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def worker(name: str, delay: float, fail: bool = False):
    logging.info(f"Worker '{name}' starting...")
    await asyncio.sleep(delay)
    if fail:
        raise ValueError(f"Worker '{name}' failed intentionally!")
    logging.info(f"Worker '{name}' finished successfully.")
    return f"Result from {name}"

async def main():
    try:
        async with TaskGroup() as group:
            # Log errors immediately using the on_error event
            group.on_error.add_listener(lambda err: logging.error(f"TaskGroup caught error: {err}"))

            group.create_task(worker("A", 1.0))
            group.create_task(worker("B", 0.5, fail=True)) # This will fail first
            group.create_task(worker("C", 1.5)) # This will likely be cancelled

            logging.info("Tasks created, group waiting...")
        # Exiting the block waits for tasks and raises error if tolerance=False
        logging.info("TaskGroup finished (This might not be reached due to exception)")

    except* ValueError as eg: # Use except* for BaseExceptionGroup (Python 3.11+)
                              # For < 3.11, use `except BaseExceptionGroup as eg:`
        logging.error(f"Caught ExceptionGroup with {len(eg.exceptions)} error(s):")
        for i, err in enumerate(eg.exceptions):
            logging.error(f"  Error {i+1}: {type(err).__name__}: {err}")
    except Exception as e:
        logging.exception("Caught unexpected exception")


if __name__ == "__main__":
    asyncio.run(main())

# Expected Output (order might vary slightly):
# INFO: Tasks created, group waiting...
# INFO: Worker 'A' starting...
# INFO: Worker 'B' starting...
# INFO: Worker 'C' starting...
# <-- B finishes sleep -->
# ERROR: TaskGroup caught error: Worker 'B' failed intentionally!
# <-- Group cancels A and C -->
# ERROR: Caught ExceptionGroup with 1 error(s):
# ERROR:   Error 1: ValueError: Worker 'B' failed intentionally!
# (Workers A and C might log Cancellation internally but won't finish normally)
```

### Error Tolerance and Uncancellable Tasks

```python
import asyncio
import logging
from aioservicekit import TaskGroup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def worker(name: str, delay: float, fail: bool = False):
    try:
        logging.info(f"Worker '{name}' starting...")
        await asyncio.sleep(delay)
        if fail:
            raise ValueError(f"Worker '{name}' failed intentionally!")
        logging.info(f"Worker '{name}' finished successfully.")
        return f"Result from {name}"
    except asyncio.CancelledError:
        logging.warning(f"Worker '{name}' was cancelled.")
        raise
    except Exception as e:
        logging.error(f"Worker '{name}' raised exception: {e}")
        raise

async def cleanup_worker(name: str, delay: float):
    logging.info(f"Cleanup worker '{name}' starting (uncancellable)...")
    await asyncio.sleep(delay)
    logging.info(f"Cleanup worker '{name}' finished.")

async def main():
    # Use error_tolerance=True
    async with TaskGroup(error_tolerance=True) as group:
        group.on_error.add_listener(lambda err: logging.error(f"TaskGroup caught error: {err}"))

        group.create_task(worker("A", 1.0))
        group.create_task(worker("B", 0.5, fail=True)) # Will fail, but others continue
        group.create_task(worker("C", 1.5)) # Will run to completion
        # Create an uncancellable cleanup task
        group.create_task(cleanup_worker("Cleanup", 1.2), canceliable=False)

        logging.info("Tasks created (tolerance=True), group waiting...")
        # Simulate an external cancellation request after a short delay
        # await asyncio.sleep(0.7)
        # logging.info(">>> Explicitly cancelling group <<<")
        # group.cancel() # This would cancel A and C, but not Cleanup

    # Exiting the block waits for ALL tasks (A, B, C, Cleanup)
    # No exception is raised here because error_tolerance=True
    logging.info("TaskGroup finished.")

    # Check collected errors
    if group.error:
        logging.warning(f"Collected {len(group.error)} error(s):")
        for i, err in enumerate(group.error):
            logging.warning(f"  Error {i+1}: {type(err).__name__}: {err}")
    else:
        logging.info("No errors collected.")


if __name__ == "__main__":
    asyncio.run(main())

# Expected Output (order might vary):
# INFO: Tasks created (tolerance=True), group waiting...
# INFO: Worker 'A' starting...
# INFO: Worker 'B' starting...
# INFO: Worker 'C' starting...
# INFO: Cleanup worker 'Cleanup' starting (uncancellable)...
# <-- B finishes sleep & fails -->
# ERROR: Worker 'B' raised exception: Worker 'B' failed intentionally!
# ERROR: TaskGroup caught error: Worker 'B' failed intentionally!
# <-- A finishes sleep -->
# INFO: Worker 'A' finished successfully.
# <-- Cleanup finishes sleep -->
# INFO: Cleanup worker 'Cleanup' finished.
# <-- C finishes sleep -->
# INFO: Worker 'C' finished successfully.
# INFO: TaskGroup finished.
# WARNING: Collected 1 error(s):
# WARNING:   Error 1: ValueError: Worker 'B' failed intentionally!
```

`TaskGroup` is particularly useful within `Service` implementations (it's used internally by `Service` and `Task`) or any time you need to manage a dynamic set of related concurrent operations with controlled error handling and cancellation behavior.
