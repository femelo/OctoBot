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
import websockets
import asyncio
import enum
import json

import octobot_commons.logging as bot_logging
import octobot_commons.authentication as authentication


class COMMANDS(enum.Enum):
    SUBSCRIBE = "subscribe"
    MESSAGE = "message"


class CHANNELS(enum.Enum):
    SIGNALS = "Spree::SignalChannel"


class CommunityFeed:
    INIT_TIMEOUT = 60

    def __init__(self, feed_url, authentication, feed_callbacks):
        self.logger: bot_logging.BotLogger = bot_logging.get_logger(
            self.__class__.__name__
        )
        self.feed_url = feed_url
        self.feed_callbacks = feed_callbacks
        self.should_stop = False
        self.websocket_connection = None
        self.consumer_task = None
        self.lock = asyncio.Lock()
        self.authentication = authentication

    async def start(self):
        await self._ensure_connection()
        if self.consumer_task is None or self.consumer_task.done():
            self.consumer_task = asyncio.create_task(self.start_consumer("default_path"))

    async def stop(self):
        self.should_stop = True
        await self.websocket_connection.close()
        self.consumer_task.cancel()

    async def start_consumer(self, path):
        while not self.should_stop:
            await self._ensure_connection()
            async for message in self.websocket_connection:
                await self.consume(message)

    async def consume(self, message):
        await self.feed_callbacks[self._get_feed(message)](message)

    async def send(self, message, command=COMMANDS.MESSAGE.value, identifier=CHANNELS.SIGNALS.value,
                   reconnect_if_necessary=True):
        if reconnect_if_necessary:
            await self._ensure_connection()
        await self.websocket_connection.send(self._build_ws_message(message, command, identifier))

    async def send_signal(self, signal_stream_id, signal_version, signal_content, reconnect_if_necessary=True):
        await self.send(
            {
                "signal_stream_id": signal_stream_id,
                "signal": signal_content,
                "version": signal_version
            },
            reconnect_if_necessary=reconnect_if_necessary
        )

    def _build_ws_message(self, message, command, identifier):
        return json.dumps({
            "command": command,
            "identifier": self._build_channel_identifier(identifier),
            "data": message
        })

    def _build_channel_identifier(self, channel_name):
        return {
            "channel": channel_name
        }

    async def _subscribe(self):
        await self.send({}, COMMANDS.SUBSCRIBE.value)
        # waiting for subscription confirmation
        async for message in self.websocket_connection:
            self.logger.debug("Waiting for subscription confirmation...")
            # resp = json.loads(await self.websocket_connection.recv())  # we can't just read message here ?
            resp = json.loads(message)
            if resp.get("type") and resp.get("type") == "confirm_subscription":
                return True
            # TODO check
            raise authentication.AuthenticationError(f"Failed to subscribe to feed: {message}")

    async def _ensure_connection(self):
        if not self.is_connected():
            async with self.lock:
                if not self.is_connected():
                    # (re)connect websocket
                    await self._connect()

    async def _connect(self):
        if self.authentication.initialized_event is not None:
            await asyncio.wait_for(self.authentication.initialized_event.wait(), self.INIT_TIMEOUT)
        if self.authentication._auth_token is None:
            raise authentication.AuthenticationRequired("OctoBot Community authentication is required to "
                                                        "use community trading signals")
        headers = {"Authorization": f"Bearer {self.authentication._auth_token}"}
        self.websocket_connection = await websockets.connect(self.feed_url, extra_headers=headers)
        await self._subscribe()
        self.logger.info("Connected to community feed")

    def is_connected(self):
        return self.websocket_connection is not None and self.websocket_connection.open

    def _get_feed(self, message):
        # TODO
        return "signals"
