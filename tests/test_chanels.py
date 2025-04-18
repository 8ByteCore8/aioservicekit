import asyncio
from unittest.mock import AsyncMock

import pytest

from aioservicekit.channels import Channel, ChannelState


@pytest.mark.asyncio
async def test_initial_state():
    chanel = Channel()
    assert chanel.state == ChannelState.initiation
    assert len(chanel.__publishers__) == 0
    assert len(chanel.__subscribers__) == 0


@pytest.mark.asyncio
async def test_state_transition_to_open():
    chanel = Channel()
    listener = AsyncMock()
    chanel.on_state_change.add_listener(listener)

    assert chanel.state == ChannelState.initiation
    publisher = await chanel.connect()
    assert chanel.state == ChannelState.initiation  # Still initiation

    subscriber = await chanel.subscribe()
    assert chanel.state == ChannelState.open  # Still initiation until task runs

    assert len(chanel.__publishers__) == 1
    assert len(chanel.__subscribers__) == 1
    listener.assert_awaited_once_with(ChannelState.open)

    await publisher.close()
    await subscriber.close()


@pytest.mark.asyncio
async def test_state_transition_to_close_on_publisher():
    chanel = Channel()
    listener = AsyncMock()
    publisher = await chanel.connect()
    subscriber = await chanel.subscribe()

    assert chanel.state == ChannelState.open
    assert len(chanel.__publishers__) == 1
    assert len(chanel.__subscribers__) == 1

    chanel.on_state_change.add_listener(listener)

    await publisher.close()
    assert chanel.state == ChannelState.closed
    listener.assert_awaited_once_with(ChannelState.closed)
    assert subscriber.__closed__ is True


@pytest.mark.asyncio
async def test_state_transition_to_close_on_subscriber():
    chanel = Channel()
    listener = AsyncMock()
    publisher = await chanel.connect()
    subscriber = await chanel.subscribe()

    assert chanel.state == ChannelState.open
    assert len(chanel.__publishers__) == 1
    assert len(chanel.__subscribers__) == 1

    chanel.on_state_change.add_listener(listener)

    await subscriber.close()
    assert chanel.state == ChannelState.closed
    listener.assert_awaited_once_with(ChannelState.closed)
    assert publisher.__closed__ is True


@pytest.mark.asyncio
async def test_state_transition_to_close_on_channel():
    channel = Channel()
    listener = AsyncMock()
    publisher = await channel.connect()
    subscriber = await channel.subscribe()

    assert channel.state == ChannelState.open
    assert len(channel.__publishers__) == 1
    assert len(channel.__subscribers__) == 1

    channel.on_state_change.add_listener(listener)

    await channel.close()
    assert channel.state == ChannelState.closed
    listener.assert_awaited_once_with(ChannelState.closed)
    assert publisher.__closed__ is True
    assert subscriber.__closed__ is True


@pytest.mark.asyncio
async def test_send_receive_single_subscriber():
    channel = Channel[str]()
    async with (
        await channel.connect() as publisher,
        await channel.subscribe() as subscriber,
    ):
        await publisher.send("hello")
        await publisher.send("world")

        assert await subscriber.read() == "hello"
        assert await subscriber.read() == "world"


@pytest.mark.asyncio
async def test_send_receive_multiple_subscribers():
    channel = Channel()
    async with (
        await channel.connect() as publisher,
        await channel.subscribe() as sub1,
        await channel.subscribe() as sub2,
    ):
        await publisher.send(1)
        await publisher.send(2)

        # Check sub1
        assert await sub1.read() == 1
        assert await sub1.read() == 2

        # Check sub2
        assert await sub2.read() == 1
        assert await sub2.read() == 2


@pytest.mark.asyncio
async def test_subscriber_iteration():
    channel = Channel[str]()
    async with (
        await channel.subscribe() as subscriber,
    ):
        async with await channel.connect() as publisher:
            await publisher.send("item1")
            await publisher.send("item2")
            await publisher.send("item3")

        results = []
        async for item in subscriber:
            results.append(item)

        assert results == ["item1", "item2", "item3"]


@pytest.mark.asyncio
async def test_subscriber_read_blocks_when_empty():
    channel = Channel()
    async with (
        await channel.connect() as publisher,
        await channel.subscribe() as subscriber,
    ):
        read_task = asyncio.create_task(subscriber.read())
        await asyncio.sleep(0.1)  # Give read task time to block
        assert read_task.done() is False

        await publisher.send(99)
        await asyncio.sleep(0.1)

        assert read_task.done() is True
        assert await read_task == 99


@pytest.mark.asyncio
async def test_subscriber_buffer_limit():
    buffer_size = 2
    channel = Channel(buffer_size=buffer_size)  # Default for subscriber

    async with (
        await channel.connect() as publisher,
        await channel.subscribe() as subscriber,
    ):
        await publisher.send(1)
        await publisher.send(2)

        # Buffer is now full (size 2)
        assert len(subscriber.__buffer__) == buffer_size
        # The internal __send__ should block now
        assert subscriber.__write_lock__.is_set() is False

        # Start sending the 3rd item, it should block inside subscriber.__send__
        send_task = asyncio.create_task(publisher.send(3))
        await asyncio.sleep(0.1)  # Give send task time to reach the block
        assert send_task.done() is False
        # Buffer should still be full
        assert len(subscriber.__buffer__) == buffer_size

        # Read an item, freeing up buffer space
        item = await subscriber.read()
        assert item == 1
        assert len(subscriber.__buffer__) == buffer_size - 1  # One item read
        # Write lock should be set again
        assert subscriber.__write_lock__.is_set() is True

        await asyncio.sleep(0.1)  # Allow send_task to complete
        assert send_task.done()  # Send task should now be complete
        await send_task  # Raise exceptions if any

        # Buffer should contain the 2nd and 3rd items
        assert len(subscriber.__buffer__) == buffer_size

        assert await subscriber.read() == 2
        assert await subscriber.read() == 3


@pytest.mark.asyncio
async def test_subscriber_buffer_override():
    channel = Channel(buffer_size=5)  # Chanel default
    subscriber = await channel.subscribe(buffer_size=1)  # Override
    assert subscriber.__buffer_size__ == 1
    await subscriber.close()


@pytest.mark.asyncio
async def test_state_listeners_removed_on_disconnect():
    channel = Channel()
    pub = await channel.connect()
    sub = await channel.subscribe()

    # Get refs to internal listeners
    pub_listener = pub.__on_channel_state_change__
    sub_listener = sub.__on_channel_state_change__

    assert pub_listener in channel.on_state_change.__listeners__
    assert sub_listener in channel.on_state_change.__listeners__

    await channel.close()
    # Publisher should also be closed/disconnected due to channel closing
    assert channel.state == ChannelState.closed
    assert sub_listener not in channel.on_state_change.__listeners__
    assert pub_listener not in channel.on_state_change.__listeners__

    # Explicitly check publisher closed state if test assumptions change
    assert pub.__closed__
