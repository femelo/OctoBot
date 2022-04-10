#  This file is part of OctoBot (https://github.com/Drakkar-Software/OctoBot)
#  Copyright (c) 2021 Drakkar-Software, All rights reserved.
#
#  OctoBot is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.
#
#  OctoBot is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  General Public License for more details.
#
#  You should have received a copy of the GNU General Public
#  License along with OctoBot. If not, see <https://www.gnu.org/licenses/>.
import pytest
import mock
import asyncio
import json
import time
import websockets

import octobot.community as community
import octobot_commons.asyncio_tools as asyncio_tools
import octobot_trading.trading_signals as trading_signals

# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio

HOST = "localhost"
PORT = 8765
TOKEN = "acb1"

DATA_DICT = {
    "data": "yes",
    "content": {
        "hi": 1,
        "a": [
            "@@@",
            1
        ]
    }
}


class MockedResponse:
    def __init__(self, status_code=200, json=None):
        self.status_code = status_code
        self.json_resp = json

    def json(self):
        return self.json_resp


def _mocked_signal():
    return trading_signals.TradingSignal("identifier", "strategy", "version", "exchange", "future", "symbol",
                                         "description", "state", "orders")


async def echo_or_signal_reply_handler(websocket, path):
    async for message in websocket:
        if "signal" == message:
            await websocket.send(json.dumps(_mocked_signal().to_dict()))
        else:
            await websocket.send(f"echo {message}")


@pytest.fixture
async def community_echo_server():
    async with websockets.serve(echo_or_signal_reply_handler, HOST, PORT):
        yield


@pytest.fixture
async def community_mocked_consumer_server():
    mock_consumer = mock.AsyncMock()

    async def mock_handler(websocket, path):
        async for message in websocket:
            await mock_consumer(message)
            await websocket.send(f"{mock_consumer.call_count}")
    async with websockets.serve(mock_handler, HOST, PORT):
        yield mock_consumer


@pytest.fixture
async def connected_community_feed():
    feed = None
    try:
        feed = community.CommunityFeed(f"ws://{HOST}:{PORT}", TOKEN, {"signals": mock.AsyncMock()})
        await feed.start()
        yield feed
    finally:
        if feed is not None:
            await feed.stop()


async def test_consume_base_message(community_echo_server, connected_community_feed):
    consume_mock = connected_community_feed.feed_callbacks["signals"]
    consume_mock.assert_not_called()
    await connected_community_feed.send("hiiiii")
    await _wait_for_receive()
    consume_mock.assert_called_once_with("echo hiiiii")
    consume_mock.reset_mock()

    await connected_community_feed.send(json.dumps(DATA_DICT))
    await _wait_for_receive()
    consume_mock.assert_called_once_with(f"echo {json.dumps(DATA_DICT)}")


async def test_consume_signal_message(community_echo_server, connected_community_feed):
    consume_mock = connected_community_feed.feed_callbacks["signals"]
    consume_mock.assert_not_called()
    await connected_community_feed.send("signal")
    await _wait_for_receive()
    consume_mock.assert_called_once_with(json.dumps(_mocked_signal().to_dict()))


async def test_send_base_message(community_mocked_consumer_server, connected_community_feed):
    consume_mock = connected_community_feed.feed_callbacks["signals"]
    consume_mock.assert_not_called()
    await connected_community_feed.send("signal")
    await _wait_for_receive()
    community_mocked_consumer_server.assert_called_once_with("signal")
    consume_mock.assert_called_once_with("1")
    consume_mock.reset_mock()

    await connected_community_feed.send(json.dumps(DATA_DICT))
    await _wait_for_receive()
    assert community_mocked_consumer_server.call_count == 2
    assert community_mocked_consumer_server.mock_calls[1].args == (json.dumps(DATA_DICT), )
    consume_mock.assert_called_once_with("2")


async def test_send_signal_message(community_mocked_consumer_server, connected_community_feed):
    consume_mock = connected_community_feed.feed_callbacks["signals"]
    consume_mock.assert_not_called()
    await connected_community_feed.send(json.dumps(_mocked_signal().to_dict()))
    await _wait_for_receive()
    community_mocked_consumer_server.assert_called_once_with(json.dumps(_mocked_signal().to_dict()))
    consume_mock.assert_called_once_with("1")


async def test_reconnect():
    server = client = None
    try:
        server = await websockets.serve(echo_or_signal_reply_handler, HOST, PORT)
        client_handler = mock.AsyncMock()
        client = community.CommunityFeed(f"ws://{HOST}:{PORT}", TOKEN, {"signals": client_handler})
        await client.start()

        # 1. ensure client is both receiving and sending messages
        client_handler.assert_not_called()
        await client.send("plop")
        await _wait_for_receive()
        client_handler.assert_called_once_with("echo plop")
        client_handler.reset_mock()
        await client.send("hii")
        await _wait_for_receive()
        client_handler.assert_called_once_with("echo hii")
        client_handler.reset_mock()

        # 2. client is disconnected (server closes)
        server.close()
        await server.wait_closed()
        with pytest.raises(websockets.ConnectionClosed):
            await client.send("hii", reconnect_if_necessary=False)
        await _wait_for_receive()
        client_handler.assert_not_called()

        # 3. client is reconnected (server restarts)
        server = await websockets.serve(echo_or_signal_reply_handler, HOST, PORT)
        # ensure the previous message was not get sent upon reconnection
        client_handler.assert_not_called()

        # 4. re-exchange message using the same client (reconnected through send method)
        assert not client.is_connected()
        await client.send("plop")
        assert client.is_connected()
        await _wait_for_receive()
        client_handler.assert_called_once_with("echo plop")
        client_handler.reset_mock()
        await client.send("hii")
        await _wait_for_receive()
        client_handler.assert_called_once_with("echo hii")
        client_handler.reset_mock()

        # 5. re disconnect server
        server.close()
        await server.wait_closed()
        with pytest.raises(websockets.ConnectionClosed):
            await client.send("hii", reconnect_if_necessary=False)
        await _wait_for_receive()
        client_handler.assert_not_called()

        # 6. wait for client reconnection, receive signal as soon as possible
        server = await websockets.serve(echo_or_signal_reply_handler, HOST, PORT)
        client_handler.assert_not_called()
        # wait for client reconnection
        t0 = time.time()
        while time.time() - t0 < 5:
            if client.is_connected():
                break
            else:
                await asyncio.sleep(0.05)
        assert client.is_connected()

        # 7. send message from server with a consuming only client
        await next(iter(server.websockets)).send("greetings")
        await _wait_for_receive()
        assert client.is_connected()
        # client_handler is called as the consume task did reconnect the client
        client_handler.assert_called_once_with("greetings")

    finally:
        if client is not None:
            await client.stop()
        if server is not None:
            server.close()
            await server.wait_closed()


async def _wait_for_receive(wait_cycles=5):
    # 5 necessary wait_cycles for both sending, receiving, replying and receiving a reply
    for _ in range(wait_cycles):
        # wait for websockets lib trigger client
        await asyncio_tools.wait_asyncio_next_cycle()
