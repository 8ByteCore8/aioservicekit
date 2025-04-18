import asyncio
from unittest.mock import AsyncMock, call

import pytest

from aioservicekit.services import Service, ServiceState, service


class MockService(Service):
    def __init__(self, work_mock=None, **kwargs):
        super().__init__(**kwargs)
        self.work_mock = work_mock or AsyncMock()

    async def __work__(self):
        await self.work_mock()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_initial_state():
    svc = MockService()
    assert svc.state == ServiceState.STOPED
    assert svc.name == "MockService"
    assert not svc.run


@pytest.mark.asyncio
async def test_custom_name():
    svc = MockService(name="CustomName")
    assert svc.name == "CustomName"


@pytest.mark.asyncio
async def test_basic_lifecycle():
    svc = MockService()
    state_change_listener = AsyncMock()
    svc.on_state_change.add_listener(state_change_listener)

    # Test start
    await svc.start()
    assert svc.state == ServiceState.RUNNING
    assert svc.run
    state_change_listener.assert_has_calls(
        [call(ServiceState.STARTING), call(ServiceState.RUNNING)]
    )

    # Test stop
    svc.stop()
    await svc.wait()
    assert svc.state == ServiceState.STOPED
    assert not svc.run
    state_change_listener.assert_has_calls(
        [call(ServiceState.STOPING), call(ServiceState.STOPED)]
    )


@pytest.mark.asyncio
async def test_service_with_dependencies():
    dep_service = MockService(name="Dependency")
    main_service = MockService(name="Main", dependences=[dep_service])

    # Start main service which should start dependency
    await main_service.start()

    assert dep_service.state == ServiceState.RUNNING
    assert main_service.state == ServiceState.RUNNING

    # Stop dependency should trigger main service stop
    dep_service.stop()
    await main_service.wait()

    assert dep_service.state == ServiceState.STOPED
    assert main_service.state == ServiceState.STOPED


@pytest.mark.asyncio
async def test_service_error_handling():
    error_mock = AsyncMock()
    svc = MockService()
    svc.on_error.add_listener(error_mock)

    # Setup work to raise an exception
    exception = Exception("Test error")
    svc.work_mock.side_effect = exception

    await svc.start()
    await asyncio.sleep(0.1)  # Allow error to propagate

    # Error should be emitted
    error_mock.assert_awaited_with(exception)
    svc.stop()


@pytest.mark.asyncio
async def test_function_service():
    work_mock = AsyncMock()

    @service()
    async def test_service():
        await work_mock()
        await asyncio.sleep(0)

    svc = test_service()
    await svc.start()
    await asyncio.sleep(0.1)

    assert work_mock.called

    svc.stop()
    await svc.wait()


@pytest.mark.asyncio
async def test_service_hooks():
    start_mock = AsyncMock()
    stop_mock = AsyncMock()

    class HookedService(MockService):
        def __on_start__(self):
            return start_mock()

        def __on_stop__(self):
            return stop_mock()

    svc = HookedService()
    await svc.start()
    start_mock.assert_awaited_once()

    svc.stop()
    await svc.wait()
    stop_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_creation():
    svc = MockService()
    await svc.start()

    task_mock = AsyncMock()
    task = svc.create_task(task_mock())

    assert isinstance(task, asyncio.Task)
    await asyncio.sleep(0.1)
    task_mock.assert_awaited_once()

    svc.stop()
    await svc.wait()
