import asyncio
from unittest.mock import AsyncMock

import pytest
from exceptiongroup import BaseExceptionGroup

from aioservicekit.groups import TaskGroup


@pytest.mark.asyncio
async def test_initial_state():
    group = TaskGroup()
    assert len(group.__tasks__) == 0
    assert len(group.__uncanceliable_tasks__) == 0
    assert len(group.__errors__) == 0
    assert group.__error_tolerance__ is False


@pytest.mark.asyncio
async def test_create_task():
    async def dummy_coro():
        return 42

    group = TaskGroup()
    task = group.create_task(dummy_coro())

    assert isinstance(task, asyncio.Task)
    assert task in group.__tasks__
    assert task not in group.__uncanceliable_tasks__

    result = await task
    assert result == 42
    assert task not in group.__tasks__  # Task should be removed after completion


@pytest.mark.asyncio
async def test_create_uncancelable_task():
    async def dummy_coro():
        return 42

    group = TaskGroup()
    task = group.create_task(dummy_coro(), canceliable=False)

    assert isinstance(task, asyncio.Task)
    assert task not in group.__tasks__
    assert task in group.__uncanceliable_tasks__

    result = await task
    assert result == 42
    assert task not in group.__uncanceliable_tasks__


@pytest.mark.asyncio
async def test_error_handling_without_tolerance():
    error_handler = AsyncMock()

    async def failing_coro():
        raise ValueError("test error")

    async def good_coro():
        await asyncio.sleep(0.1)
        return 42

    group = TaskGroup(error_tolerance=False)
    group.on_error.add_listener(error_handler)

    group.create_task(failing_coro())
    good_task = group.create_task(good_coro())

    with pytest.raises(BaseExceptionGroup) as exc_info:
        await group.wait()

    assert len(exc_info.value.exceptions) == 1
    assert isinstance(exc_info.value.exceptions[0], ValueError)
    assert str(exc_info.value.exceptions[0]) == "test error"

    error_handler.assert_awaited_once()
    assert good_task.cancelled()


@pytest.mark.asyncio
async def test_error_handling_with_tolerance():
    error_handler = AsyncMock()

    async def failing_coro():
        raise ValueError("test error")

    async def good_coro():
        await asyncio.sleep(0.1)
        return 42

    group = TaskGroup(error_tolerance=True)
    group.on_error.add_listener(error_handler)

    group.create_task(failing_coro())
    good_task = group.create_task(good_coro())

    await group.wait()  # Should not raise

    error_handler.assert_awaited_once()
    assert not good_task.cancelled()
    assert good_task.result() == 42


@pytest.mark.asyncio
async def test_context_manager():
    results = []

    async def task_coro():
        await asyncio.sleep(0.1)
        results.append(42)

    async with TaskGroup() as group:
        group.create_task(task_coro())
        group.create_task(task_coro())

    assert results == [42, 42]


@pytest.mark.asyncio
async def test_cancel():
    cancel_count = 0

    async def cancelable_coro():
        nonlocal cancel_count
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            cancel_count += 1
            raise

    async def uncancelable_coro():
        await asyncio.sleep(1)
        return 42

    group = TaskGroup()

    # Create mix of cancelable and uncancelable tasks
    group.create_task(cancelable_coro())
    group.create_task(cancelable_coro())
    uncancelable_task = group.create_task(uncancelable_coro(), canceliable=False)
    await asyncio.sleep(0)  # Run tasks

    group.cancel()
    await group.wait()

    assert cancel_count == 2  # Both cancelable tasks should have been cancelled
    assert uncancelable_task.result() == 42  # Uncancelable task should complete


@pytest.mark.asyncio
async def test_reset_errors():
    async def failing_coro():
        raise ValueError("test error")

    group = TaskGroup(error_tolerance=True)
    group.create_task(failing_coro())

    await group.wait()
    assert len(group.errors) == 0  # Error tolerance means errors aren't collected

    # Manually add an error and test reset
    group.__errors__.append(ValueError())
    assert len(group.errors) == 1

    group.reset_errors()
    assert len(group.errors) == 0
