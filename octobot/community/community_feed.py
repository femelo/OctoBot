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

import octobot_commons.logging as bot_logging


class CommunityFeed:
    def __init__(self, feed_url, auth_token, feed_callbacks):
        self.logger: bot_logging.BotLogger = bot_logging.get_logger(
            self.__class__.__name__
        )
        self.feed_url = feed_url
        self.auth_token = auth_token
        self.feed_callbacks = feed_callbacks
        self.should_stop = False
        self.websocket_connection = None
        self.consumer_task = None
        self.lock = asyncio.Lock()

    async def start(self):
        await self._ensure_connection()
        if self.consumer_task is None or self.consumer_task.done():
            self.consumer_task = asyncio.create_task(self.start_consumer("'hello path'"))

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

    async def send(self, message, reconnect_if_necessary=True):
        if reconnect_if_necessary:
            await self._ensure_connection()
        await self.websocket_connection.send(message)

    async def _ensure_connection(self):
        if not self.is_connected():
            async with self.lock:
                if not self.is_connected():
                    # (re)connect websocket
                    await self._connect()

    async def _connect(self):
        self.websocket_connection = await websockets.connect(self.feed_url)
        self.logger.info("Connected to community feed")

    def is_connected(self):
        return self.websocket_connection is not None and self.websocket_connection.open

    def _get_feed(self, message):
        # TODO
        return "signals"
