"""Trello API client for creating cards."""

import logging
from typing import Optional

import httpx

from granola_bridge.config import AppConfig

logger = logging.getLogger(__name__)


class TrelloError(Exception):
    """Error from Trello API."""

    pass


class TrelloClient:
    """Client for Trello REST API."""

    def __init__(self, config: AppConfig):
        self.base_url = config.trello.api_base_url.rstrip("/")
        self.api_key = config.env.trello_api_key
        self.api_token = config.env.trello_api_token
        self.list_id = config.env.trello_list_id

        if not self.api_key or not self.api_token:
            logger.warning("Trello API credentials not configured")

    def _auth_params(self) -> dict[str, str]:
        """Get authentication query parameters."""
        return {
            "key": self.api_key,
            "token": self.api_token,
        }

    async def create_card(
        self,
        name: str,
        desc: str = "",
        list_id: Optional[str] = None,
        labels: Optional[list[str]] = None,
        due: Optional[str] = None,
    ) -> dict:
        """Create a new Trello card.

        Args:
            name: Card title
            desc: Card description (supports Markdown)
            list_id: Target list ID (uses default if not specified)
            labels: List of label IDs to attach
            due: Due date in ISO format

        Returns:
            Created card data including id, url, shortUrl

        Raises:
            TrelloError: If the API request fails
        """
        target_list = list_id or self.list_id

        if not target_list:
            raise TrelloError("No Trello list ID configured")

        params = {
            **self._auth_params(),
            "idList": target_list,
            "name": name,
            "desc": desc,
        }

        if labels:
            params["idLabels"] = ",".join(labels)
        if due:
            params["due"] = due

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.base_url}/cards",
                    params=params,
                )

                if response.status_code == 401:
                    raise TrelloError("Invalid Trello API credentials")
                if response.status_code == 404:
                    raise TrelloError(f"Trello list not found: {target_list}")
                if response.status_code != 200:
                    raise TrelloError(f"Trello API error: {response.status_code} - {response.text}")

                card = response.json()
                logger.info(f"Created Trello card: {card.get('shortUrl')}")
                return card

        except httpx.RequestError as e:
            logger.error(f"Failed to create Trello card: {e}")
            raise TrelloError(f"Network error: {e}")

    async def get_card(self, card_id: str) -> dict:
        """Get a card by ID.

        Args:
            card_id: The card ID

        Returns:
            Card data
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{self.base_url}/cards/{card_id}",
                    params=self._auth_params(),
                )

                if response.status_code != 200:
                    raise TrelloError(f"Failed to get card: {response.status_code}")

                return response.json()

        except httpx.RequestError as e:
            raise TrelloError(f"Network error: {e}")

    async def update_card(
        self,
        card_id: str,
        name: Optional[str] = None,
        desc: Optional[str] = None,
        closed: Optional[bool] = None,
    ) -> dict:
        """Update an existing card.

        Args:
            card_id: The card ID to update
            name: New card title
            desc: New description
            closed: Archive the card if True

        Returns:
            Updated card data
        """
        params = self._auth_params()

        if name is not None:
            params["name"] = name
        if desc is not None:
            params["desc"] = desc
        if closed is not None:
            params["closed"] = str(closed).lower()

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.put(
                    f"{self.base_url}/cards/{card_id}",
                    params=params,
                )

                if response.status_code != 200:
                    raise TrelloError(f"Failed to update card: {response.status_code}")

                return response.json()

        except httpx.RequestError as e:
            raise TrelloError(f"Network error: {e}")

    async def get_lists(self, board_id: str) -> list[dict]:
        """Get all lists on a board.

        Args:
            board_id: The board ID

        Returns:
            List of list objects
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{self.base_url}/boards/{board_id}/lists",
                    params=self._auth_params(),
                )

                if response.status_code != 200:
                    raise TrelloError(f"Failed to get lists: {response.status_code}")

                return response.json()

        except httpx.RequestError as e:
            raise TrelloError(f"Network error: {e}")

    async def health_check(self) -> bool:
        """Check if Trello API is accessible with current credentials."""
        if not self.api_key or not self.api_token:
            return False

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.base_url}/members/me",
                    params=self._auth_params(),
                )
                return response.status_code == 200

        except Exception:
            return False
