# aioservicekit

Welcome to the documentation for `aioservicekit`.

`aioservicekit` is a Python library built on `asyncio` designed to provide a robust and structured framework for creating long-running asynchronous services, periodic tasks, and managing their lifecycles gracefully.

## Core Features

*   **Managed Services:** Define services with clear `start`, `stop`, `restart`, and `wait` lifecycles.
*   **Periodic Tasks:** Easily create tasks that run at regular intervals.
*   **Dependency Management:** Define dependencies between services, ensuring correct startup and shutdown order.
*   **Graceful Shutdown:** Integrates with OS signals (SIGINT, SIGTERM) for clean application termination via the `on_shutdown` event.
*   **Task Concurrency:** Manage groups of concurrent tasks with configurable error handling using `TaskGroup`.
*   **Pub/Sub Channels:** Distribute data asynchronously to multiple consumers using `Chanel`.
*   **Event System:** A generic event emitter/listener pattern for decoupling components.
*   **Utilities:** Helpers for running multiple services and ensuring clean application exit.

## Navigation

*   [Getting Started](./docs/getting_started.md)
*   [Services](./docs/services.md)
*   [Periodic Tasks](./docs/tasks.md)
*   [Channels (Pub/Sub)](./docs/channels.md)
*   [Events](./docs/events.md)
*   [Task Groups](./docs/task_groups.md)
*   [Utilities](./docs/utils.md)

## Installation

```bash
pip install aioservicekit
```

Ready to build robust async applications? Head over to the [Getting Started](./docs/getting_started.md) guide!
