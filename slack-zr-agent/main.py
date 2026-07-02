from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from slack_sdk.web.async_client import AsyncWebClient

from slack_app.handlers import app, send_permission_request, start_socket_mode
from zr.config import (
    SCHEDULE_ENABLED,
    SCHEDULE_HOUR,
    SCHEDULE_MINUTE,
    SLACK_BOT_TOKEN,
    SLACK_NOTIFY_USER_ID,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def scheduled_permission_prompt() -> None:
    client = AsyncWebClient(token=SLACK_BOT_TOKEN)
    await send_permission_request(client, user_id=SLACK_NOTIFY_USER_ID)
    logger.info("Scheduled ZipRecruiter permission prompt sent to %s", SLACK_NOTIFY_USER_ID)


async def main() -> None:
    scheduler = AsyncIOScheduler()
    if SCHEDULE_ENABLED:
        scheduler.add_job(
            scheduled_permission_prompt,
            trigger="cron",
            hour=SCHEDULE_HOUR,
            minute=SCHEDULE_MINUTE,
        )
        scheduler.start()
        logger.info(
            "Scheduler enabled: daily prompt at %02d:%02d",
            SCHEDULE_HOUR,
            SCHEDULE_MINUTE,
        )

    logger.info("Starting Slack ZipRecruiter agent (Socket Mode)...")
    await start_socket_mode()


if __name__ == "__main__":
    asyncio.run(main())
