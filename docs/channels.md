# Channels (Publish/Subscribe)

`aioservicekit` provides a simple, asynchronous publish/subscribe mechanism through `Channel`. This allows one part of your application to broadcast data to multiple interested listeners concurrently.

## Concept

* **`Channel`**: The central hub or broadcaster. Publishers send data *to* the `Channel`.
* **`_ChannelSubscriber`**: A subscriber connected *to* a `Channel`. Each subscriber receives a copy of the data sent to the channel and buffers it locally. Consumers read data *from* their `_ChannelSubscriber`.
* **`_ChannelPublisher`**: A publisher connected *to* a `Channel`. Each publisher can send data to the channel which is then distributed to all subscribers. Multiple publishers can share the same channel.

This creates a fan-out pattern where one message sent to the `Channel` is delivered to all currently connected `_ChannelSubscriber`s.

## Core Components

### `Channel[T]`

* Generic channel type that supports multiple publishers and subscribers
* `__init__(self, buffer_size: int = 0)`: Creates a channel. `buffer_size` is the *default* buffer size for subscribers (0 means unbounded).
* `async subscribe(self, *, buffer_size: Optional[int] = None) -> _ChannelSubscriber[T]`: Creates and returns a new subscriber. Buffer size can be overridden per subscriber.
* `async connect(self) -> _ChannelPublisher[T]`: Creates and returns a new publisher.
* `async close(self)`: Closes the channel.
* `state` property: Access the current `ChannelState` (initiation, open, closed)

### `_ChannelSubscriber[T]`

* Internal subscriber implementation for receiving messages
* Created via `Channel.subscribe()`
* `async read(self) -> T`: Reads next message from buffer
* Supports async iteration with `async for`
* Buffer size can be configured per subscriber
* `async close(self)`: Disconnect from channel

### `_ChannelPublisher[T]`

* Internal publisher implementation for sending messages
* Created via `Channel.connect()`
* `async send(self, data: T)`: Send data to all subscribers concurrently
* `async close(self)`: Disconnect from channel
* Handles back-pressure from slow subscribers automatically
* Can be used as an async context manager with `async with`
* Multiple publishers can share a single channel
* Thread-safe for concurrent publishing
* Raises `ChannelClosedError` if channel is closed

## Example: Broadcasting Events

Imagine a service detecting system events and broadcasting them to multiple listeners (e.g., a logger, an alerter).

```python
import asyncio
import logging
import random
from typing import NamedTuple

import aioservicekit
from aioservicekit import Channel, Service

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


# Define the data structure for events
class SystemEvent(NamedTuple):
    timestamp: float
    source: str
    message: str
    level: str


# Create a global channel for system events
# Default subscriber buffer size is 5
system_events = Channel[SystemEvent](buffer_size=5)


# --- Producer Service ---
class EventDetector(Service):
    async def __on_start__(self) -> None:
        self.publisher = await system_events.connect()

    async def __on_stop__(self) -> None:
        await self.publisher.close()

    async def __work__(self) -> None:
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
            await self.publisher.send(event)
        except Exception:
            logging.exception("Error sending event!")


# --- Consumer Services ---


class EventLogger(Service):
    async def __on_start__(self) -> None:
        self.subscriber = await system_events.subscribe()

    async def __on_stop__(self) -> None:
        await self.subscriber.close()

    async def __work__(self) -> None:
        logging.info(f"Consumer '{self.name}' starting...")
        async for event in self.subscriber:
            log_func = getattr(logging, event.level.lower(), logging.info)
            log_func(
                f"'{self.name}' received: {event.message} (Source: {event.source})"
            )


class ErrorAlerter(Service):
    async def __on_start__(self) -> None:
        self.subscriber = await system_events.subscribe()

    async def __on_stop__(self) -> None:
        await self.subscriber.close()

    async def __work__(self) -> None:
        logging.info("Alerter starting...")
        async for event in self.subscriber:
            if event.level == "ERROR":
                logging.critical(f"!!! ALERT from '{self.name}': {event.message} !!!")
            else:
                logging.debug(f"Alerter '{self.name}' skipping event: {event.level}")


# --- Main Application ---
@aioservicekit.main
async def main():
    logger = EventLogger()
    alerter = ErrorAlerter()
    detector = EventDetector(dependences=[logger, alerter])

    logging.info("Starting application with event detector and consumers...")
    async with aioservicekit.run_services([detector, logger, alerter]) as waiter:
        logging.info("Services running. Press Ctrl+C to stop.")
        await waiter
    logging.info("Application shut down gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Shutdown requested.")

```

This example demonstrates:
* A single `Channel` instance
* One producer service (`EventDetector`) publishing events
* Multiple consumer services (`EventLogger`, `ErrorAlerter`) subscribing to events
* Using async context managers to handle connection lifecycles
* Different subscribers can have different buffer sizes and processing logic

Channels are useful for decoupling parts of your application that need to react to the same stream of data or events.
