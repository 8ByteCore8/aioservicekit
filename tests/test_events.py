from unittest.mock import AsyncMock, call

import pytest

from aioservicekit import Event


@pytest.mark.asyncio
async def test_initial_state():
    event = Event()
    assert len(event.__listeners__) == 0


@pytest.mark.asyncio
async def test_listeners():
    event = Event()
    mock_callback = AsyncMock()

    event.add_listener(mock_callback)
    assert len(event.__listeners__) == 1
    assert mock_callback in event.__listeners__

    event.remove_listener(mock_callback)
    assert len(event.__listeners__) == 0
    assert mock_callback not in event.__listeners__


@pytest.mark.asyncio
async def test_emit_single_listener():
    event = Event()
    mock_callback = AsyncMock()

    event.add_listener(mock_callback)
    await event.emit(42)

    mock_callback.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_emit_multiple_listeners():
    event = Event()
    mock_callbacks = [AsyncMock() for _ in range(3)]

    for callback in mock_callbacks:
        event.add_listener(callback)

    await event.emit(42)

    for callback in mock_callbacks:
        callback.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_emit_different_values():
    event = Event()
    mock_callback = AsyncMock()

    event.add_listener(mock_callback)

    test_values = [1, 2, 3]
    for value in test_values:
        await event.emit(value)

    assert mock_callback.await_count == len(test_values)
    mock_callback.assert_has_awaits([call(value) for value in test_values])


@pytest.mark.asyncio
async def test_emit_with_no_listeners():
    event = Event()
    # Should not raise any exceptions
    await event.emit(42)


@pytest.mark.asyncio
async def test_listener_exception_handling():
    event = Event()

    async def failing_callback():
        raise ValueError("Test exception")

    def failing_sync_callback():
        raise ValueError("Test exception")

    mock_success = AsyncMock()

    event.add_listener(failing_callback)
    event.add_listener(failing_sync_callback)
    event.add_listener(mock_success)

    # Should not raise exception and should continue to other listeners
    await event.emit(42)

    mock_success.assert_awaited_once_with(42)
