# Events

`aioservicekit` provides a generic `Event` class for implementing the observer pattern (event emitters and listeners) asynchronously, along with a specialized `on_shutdown` event for handling application termination signals.

## `Event[P]`

The `Event` class allows you to define custom events that components can subscribe (listen) to and emit. It's typed using `typing.ParamSpec` (`P`) to ensure listeners have the correct signature for the arguments the event will be emitted with.

**Key Features:**

*   **Typed Arguments**: Define the expected arguments for listeners using `ParamSpec`.
*   **Sync/Async Listeners**: Supports both regular functions and `async def` functions as listeners.
*   **Concurrent Emission**: When an event is emitted, all async listeners are run concurrently using an internal `asyncio.TaskGroup`. Sync listeners are called sequentially before async listeners are scheduled.
*   **Context Manager**: Can be used in a `with` statement to ensure `close()` is called on exit.
*   **Error Handling**: Exceptions raised within listeners during emission are caught and suppressed (consider adding logging within your listeners if needed).

**API:**

*   `__init__(self)`: Creates a new event.
*   `add_listener(self, listener: Callable[P, None | Coroutine])`: Adds a listener function/coroutine. Raises `EventClosedError` if closed.
*   `remove_listener(self, listener: Callable[P, None | Coroutine])`: Removes a specific listener. Raises `EventClosedError` if closed.
*   `async def emit(self, *args: P.args, **kwargs: P.kwargs)`: Emits the event, calling all listeners with the provided arguments. Raises `EventClosedError` if closed.
*   `close(self)`: Marks the event as closed, clears all listeners, and prevents further emissions or listener modifications. Idempotent.
*   `is_closed` (Property): Returns `True` if the event is closed.

**Example:**

```python
import asyncio
import logging
from typing import ParamSpec
from aioservicekit import Event

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Define the parameter specification for our custom event
P_UserData = ParamSpec("P_UserData")

# Create an event that expects a user ID (int) and a data dictionary (dict)
user_data_updated_event = Event[P_UserData]()
# Type checker expects: (user_id: int, data: dict) -> None | Coroutine

# Define some listeners
def sync_listener(user_id: int, data: dict):
    logging.info(f"[Sync] User {user_id} updated data: {list(data.keys())}")

async def async_listener_1(user_id: int, data: dict):
    logging.info(f"[Async 1] Processing update for user {user_id}...")
    await asyncio.sleep(0.5)
    logging.info(f"[Async 1] Finished processing for user {user_id}")

async def async_listener_2(user_id: int, data: dict):
    logging.info(f"[Async 2] Archiving data for user {user_id}...")
    await asyncio.sleep(0.2)
    logging.info(f"[Async 2] Finished archiving for user {user_id}")

async def main():
    # Add listeners
    user_data_updated_event.add_listener(sync_listener)
    user_data_updated_event.add_listener(async_listener_1)
    user_data_updated_event.add_listener(async_listener_2)

    logging.info("Emitting event for user 101")
    # Emit the event with matching arguments
    await user_data_updated_event.emit(user_id=101, data={"name": "Alice", "email": "a@ex.com"})

    logging.info("Removing async_listener_2")
    user_data_updated_event.remove_listener(async_listener_2)

    logging.info("Emitting event for user 202")
    await user_data_updated_event.emit(user_id=202, data={"status": "active"})

    logging.info("Closing the event")
    user_data_updated_event.close()

    try:
        logging.info("Attempting to emit on closed event...")
        await user_data_updated_event.emit(user_id=303, data={})
    except Exception as e:
        logging.error(f"Caught expected error: {type(e).__name__}") # Expect EventClosedError

if __name__ == "__main__":
    asyncio.run(main())
```

## `on_shutdown()` Event

This is a globally accessible, singleton `Event` specifically designed to handle graceful shutdown signals from the operating system.

**Features:**

*   **Singleton**: Calling `on_shutdown()` multiple times returns the same `Event` instance.
*   **Signal Handling**: Automatically registers handlers for `signal.SIGINT` (Ctrl+C), `signal.SIGTERM` (standard termination signal), and `signal.SIGHUP` (hangup, often used for config reload or shutdown).
*   **Emission**: When one of the handled signals is received, it emits the `signal.Signals` enum value (e.g., `signal.SIGINT`) to all its listeners.
*   **Auto-Close**: After emitting the signal, the `on_shutdown` event automatically closes itself, preventing further emissions.
*   **Loop Agnostic**: Works correctly whether an `asyncio` event loop is currently running or not when the signal arrives.

**Usage:**

You typically add listeners to `on_shutdown()` to perform cleanup tasks when the application is requested to terminate. `aioservicekit.Service` uses this internally to trigger its `stop()` method.

```python
import asyncio
import logging
import signal
from aioservicekit import on_shutdown, main

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

async def cleanup_resources(received_signal: signal.Signals):
    logging.warning(f"Shutdown signal received: {received_signal.name}. Cleaning up...")
    # Simulate closing files, connections, etc.
    await asyncio.sleep(1)
    logging.info("Cleanup finished.")

@main
async def app_main():
    logging.info("Application started. Press Ctrl+C to trigger shutdown.")

    # Get the shutdown event and add our cleanup listener
    shutdown_event = on_shutdown()
    shutdown_event.add_listener(cleanup_resources)

    # Keep the application running until shutdown is triggered
    # Option 1: Wait on the event itself (since it closes after emit)
    # await shutdown_event.wait() # Note: Event doesn't have a public wait()

    # Option 2: Use an asyncio Future and let the signal handler stop the loop
    stop_event = asyncio.Event()
    async def signal_handler_wrapper(sig):
        # This is called *by* the on_shutdown event emission
        # We just use it to signal our main loop to stop *after* cleanup
        await cleanup_resources(sig) # Call our actual cleanup
        stop_event.set() # Now signal main to exit

    # Re-add listener using the wrapper
    # shutdown_event.remove_listener(cleanup_resources) # Remove original direct one
    # shutdown_event.add_listener(signal_handler_wrapper) # Add wrapper

    # Alternative (Simpler if cleanup_resources is the main goal):
    # Just let on_shutdown call cleanup_resources directly.
    # The loop will be stopped by KeyboardInterrupt or external signal.
    # Here, we just wait indefinitely. The @main decorator ensures cleanup finishes.
    await asyncio.Future() # Wait forever

    logging.info("Main loop exiting.") # Will run after Ctrl+C and cleanup

if __name__ == "__main__":
    try:
        asyncio.run(app_main())
    except KeyboardInterrupt:
        # This might still happen, but the signal handler inside on_shutdown
        # and our cleanup listener should have already run or been scheduled.
        logging.info("KeyboardInterrupt caught in main.")
    finally:
        logging.info("Application exiting.")

```

Using `on_shutdown()` provides a standardized way to hook into the application termination process, ensuring your cleanup logic runs reliably when the OS requests a shutdown.
