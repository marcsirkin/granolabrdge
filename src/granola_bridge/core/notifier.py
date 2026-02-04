"""Webhook notifications for Slack and Discord."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

from granola_bridge.config import AppConfig

logger = logging.getLogger(__name__)


class Notifier:
    """Send notifications via webhooks."""

    def __init__(self, config: AppConfig):
        self.slack_url = config.env.slack_webhook_url
        self.discord_url = config.env.discord_webhook_url
        self.daily_summary_enabled = config.notifications.daily_summary.enabled
        self.daily_summary_time = config.notifications.daily_summary.time

        self._running = False
        self._task: Optional[asyncio.Task] = None

    @property
    def has_webhooks(self) -> bool:
        """Check if any webhooks are configured."""
        return bool(self.slack_url or self.discord_url)

    async def send_alert(self, title: str, message: str, error: bool = False) -> None:
        """Send an alert notification.

        Args:
            title: Alert title
            message: Alert message
            error: Whether this is an error alert
        """
        if not self.has_webhooks:
            return

        tasks = []

        if self.slack_url:
            tasks.append(self._send_slack(title, message, error))

        if self.discord_url:
            tasks.append(self._send_discord(title, message, error))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def send_daily_summary(
        self,
        meetings_processed: int,
        action_items_created: int,
        cards_created: int,
        failures: int,
    ) -> None:
        """Send daily summary notification.

        Args:
            meetings_processed: Number of meetings processed today
            action_items_created: Number of action items extracted
            cards_created: Number of Trello cards created
            failures: Number of failures
        """
        if not self.has_webhooks:
            return

        message = (
            f"*Daily Summary - {datetime.now().strftime('%Y-%m-%d')}*\n"
            f"• Meetings processed: {meetings_processed}\n"
            f"• Action items extracted: {action_items_created}\n"
            f"• Trello cards created: {cards_created}\n"
        )

        if failures > 0:
            message += f"• Failures: {failures} :warning:"

        await self.send_alert("Granola Bridge Daily Summary", message)

    async def _send_slack(self, title: str, message: str, error: bool = False) -> None:
        """Send notification to Slack."""
        if not self.slack_url:
            return

        color = "#dc3545" if error else "#28a745"
        payload = {
            "attachments": [
                {
                    "color": color,
                    "title": title,
                    "text": message,
                    "ts": datetime.now().timestamp(),
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(self.slack_url, json=payload)
                if response.status_code != 200:
                    logger.error(f"Slack webhook failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")

    async def _send_discord(self, title: str, message: str, error: bool = False) -> None:
        """Send notification to Discord."""
        if not self.discord_url:
            return

        color = 0xDC3545 if error else 0x28A745
        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": color,
                    "timestamp": datetime.now().isoformat(),
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(self.discord_url, json=payload)
                if response.status_code not in (200, 204):
                    logger.error(f"Discord webhook failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")

    def start_daily_scheduler(self) -> None:
        """Start the daily summary scheduler."""
        if not self.daily_summary_enabled or not self.has_webhooks:
            return

        self._running = True
        self._task = asyncio.create_task(self._daily_scheduler_loop())
        logger.info(f"Daily summary scheduler started (time: {self.daily_summary_time})")

    async def _daily_scheduler_loop(self) -> None:
        """Loop that sends daily summaries at the configured time."""
        while self._running:
            now = datetime.now()
            target_hour, target_minute = map(int, self.daily_summary_time.split(":"))

            # Calculate next run time
            target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

            if now >= target:
                # Already past today's time, schedule for tomorrow
                target += timedelta(days=1)

            # Sleep until target time
            sleep_seconds = (target - now).total_seconds()
            logger.debug(f"Next daily summary in {sleep_seconds:.0f} seconds")

            await asyncio.sleep(sleep_seconds)

            if self._running:
                # Get stats and send summary
                # In a real implementation, this would query the database
                await self._send_daily_summary_from_db()

    async def _send_daily_summary_from_db(self) -> None:
        """Query database and send daily summary."""
        from granola_bridge.models.database import get_session_factory
        from granola_bridge.models import Meeting, ActionItem, ActionItemStatus

        SessionLocal = get_session_factory()
        session = SessionLocal()

        try:
            today = datetime.utcnow().date()
            today_start = datetime.combine(today, datetime.min.time())

            meetings = (
                session.query(Meeting)
                .filter(Meeting.created_at >= today_start)
                .count()
            )

            action_items = (
                session.query(ActionItem)
                .filter(ActionItem.created_at >= today_start)
                .count()
            )

            cards_created = (
                session.query(ActionItem)
                .filter(
                    ActionItem.created_at >= today_start,
                    ActionItem.status == ActionItemStatus.SENT,
                )
                .count()
            )

            failures = (
                session.query(ActionItem)
                .filter(
                    ActionItem.created_at >= today_start,
                    ActionItem.status == ActionItemStatus.FAILED,
                )
                .count()
            )

            await self.send_daily_summary(meetings, action_items, cards_created, failures)

        except Exception as e:
            logger.error(f"Failed to send daily summary: {e}")
        finally:
            session.close()

    def stop(self) -> None:
        """Stop the daily scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
