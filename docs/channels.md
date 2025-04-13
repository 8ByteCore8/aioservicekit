# Channels (Publish/Subscribe)

`aioservicekit` provides a simple, asynchronous publish/subscribe mechanism through `Chanel` and `ChanelCustomer`. This allows one part of your application to broadcast data to multiple interested listeners concurrently.

## Concept

*   **`Chanel`**: The central hub or broadcaster. Producers send data *to* the `Chanel`.
*   **`ChanelCustomer`**: A subscriber connected *to* a `Chanel`. Each customer receives a copy of the data sent to the channel and buffers it locally. Consumers read data *from* their `ChanelCustomer`.

This creates a fan-out pattern where one message sent to the `Chanel` is delivered to all currently connected `ChanelCustomer`s.

## Core Components

### `Chanel[T]`

*   Acts as the publisher endpoint.
*   `__init__(self, size: int = 0)`: Creates a channel. `size` is the *default* buffer size for customers connected later (0 means unbounded).
*   `async def send(self, data: T)`: Sends data to all currently connected customers. If the channel has no customers (`is_closed` is True), it waits until at least one customer connects. Sending to a customer might block if its buffer is full; these waits happen concurrently.
*   `connect(self, *, size: Optional[int] = None) -> ChanelCustomer[T]`: Creates and returns a new `ChanelCustomer` connected to this channel. The customer gets its own buffer (`size` overrides the channel default).
*   `disconnect(self, customer: ChanelCustomer[T])`: Removes a customer. Called automatically when a customer is `close()`d.
*   `is_opened` / `is_closed` (Properties): Check if any customers are connected.
*   `clone(self) -> ClonnedChanel[T]`: Creates a lightweight handle.

### `ChanelCustomer[T]`

*   Acts as the subscriber endpoint.
*   Created via `Chanel.connect()`.
*   `async def read(self) -> T`: Reads the next item from the customer's buffer. Waits if the buffer is empty. Raises `ChanelCustomerClousedError` if closed and the buffer becomes empty.
*   **Async Iteration**: Supports `async for data in customer: ...` which internally calls `read()` and handles `ChanelCustomerClousedError` by stopping iteration.
*   `close(self)`: Disconnects the customer from the `Chanel`, prevents further receives, and clears its buffer.
*   `reset(self)`: Clears the customer's buffer without closing.
*   `clone(self) -> ChanelCustomer[T]`: Convenience method to create another independent customer connected to the same original `Chanel`.

### `ClonnedChanel[T]`

*   A proxy object obtained via `Chanel.clone()`.
*   Allows calling `send()` and `connect()` on the original channel without holding a direct reference to it. Useful for decoupling producers or connection points from the main channel owner.

## Example: Broadcasting Events

Imagine a service detecting system events and broadcasting them to multiple listeners (e.g., a logger, an alerter).

```python
import asyncio
import logging
import random
from typing import NamedTuple
from aioservicekit import (
    Chanel, ChanelCustomer, service, run_services, main, TaskGroup
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Define the data structure for events
class SystemEvent(NamedTuple):
    timestamp: float
    source: str
    message: str
    level: str

# Create a global channel for system events
# Default customer buffer size is 5
system_event_chanel = Chanel[SystemEvent](size=5)

# --- Producer Service ---
@service(name="EventDetector")
async def event_detector_service():
    """Simulates detecting system events and sending them to the channel."""
    while True: # Service loop managed by @service decorator
        await asyncio.sleep(random.uniform(0.5, 2.0))
        level = random.choice(["INFO", "WARNING", "ERROR"])
        event = SystemEvent(
            timestamp=asyncio.get_event_loop().time(),
            source="Detector",
            message=f"Simulated event {random.randint(1, 100)}",
            level=level,
        )
        logging.debug(f"Detector sending: {event}")
        try:
            # Send to the channel - might wait if channel was initially closed
            await system_event_chanel.send(event)
        except Exception as e:
            logging.exception("Error sending event!")
            # In a real scenario, handle channel errors appropriately


# --- Consumer Services ---

async def process_events(customer: ChanelCustomer[SystemEvent], consumer_name: str):
    """Generic event processing logic for a consumer."""
    logging.info(f"Consumer '{consumer_name}' starting...")
    try:
        async for event in customer: # Iterate using the customer
            log_func = getattr(logging, event.level.lower(), logging.info)
            log_func(f"'{consumer_name}' received: {event.message} (Source: {event.source})")
            # Simulate processing time
            await asyncio.sleep(random.uniform(0.1, 0.3) * (1 if event.level == "INFO" else 2))
    except Exception as e:
        logging.exception(f"Consumer '{consumer_name}' error")
    finally:
        # Ensure customer is closed if the loop exits unexpectedly
        # (run_services handles this on shutdown too)
        customer.close()
        logging.info(f"Consumer '{consumer_name}' stopped.")


@service(name="EventLogger")
async def event_logger_service():
    """A service that logs all events."""
    # Connect to the channel when the service starts
    customer = system_event_chanel.connect()
    # Service's __work__ loop just runs the processor
    await process_events(customer, "Logger")


@service(name="ErrorAlerter")
async def error_alerter_service():
    """A service that only processes ERROR events."""
    customer = system_event_chanel.connect(size=2) # Smaller buffer for alerts
    logging.info("Alerter starting...")
    try:
        async for event in customer:
            if event.level == "ERROR":
                logging.critical(f"!!! ALERT from Alerter: {event.message} !!!")
                await asyncio.sleep(0.5) # Simulate sending alert
            else:
                # Skip non-error events quickly
                 logging.debug(f"Alerter skipping event: {event.level}")
                 await asyncio.sleep(0.01)
    except Exception as e:
        logging.exception("Alerter error")
    finally:
        customer.close()
        logging.info("Alerter stopped.")

# --- Main Application ---
@main
async def app_main():
    detector = event_detector_service()
    logger = event_logger_service()
    alerter = error_alerter_service()

    services_to_run = [detector, logger, alerter]

    logging.info("Starting application with event detector and consumers...")
    async with run_services(services_to_run) as waiter:
        logging.info("Services running. Press Ctrl+C to stop.")
        await waiter
    logging.info("Application shut down gracefully.")

if __name__ == "__main__":
    try:
        asyncio.run(app_main())
    except KeyboardInterrupt:
        logging.info("Shutdown requested.")

```

This example demonstrates:
*   A single `Chanel` instance.
*   One producer service (`EventDetector`) sending data to the channel.
*   Multiple consumer services (`EventLogger`, `ErrorAlerter`) connecting to the same channel.
*   Each consumer uses `async for` on its `ChanelCustomer` to receive events independently.
*   Different consumers can have different buffer sizes and processing logic.

Channels are useful for decoupling parts of your application that need to react to the same stream of data or events.
