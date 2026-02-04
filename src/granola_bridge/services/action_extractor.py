"""Extract action items from meeting transcripts using LLM."""

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from granola_bridge.services.llm_client import LLMClient, LLMError

logger = logging.getLogger(__name__)

# Note: Some local models work better with instructions in user message, not system
SYSTEM_PROMPT = None  # Disabled for better local model compatibility


@dataclass
class ExtractedActionItem:
    """An action item extracted from a transcript."""

    title: str
    description: str
    assignee: Optional[str]
    context: str


class ActionExtractor:
    """Extract action items from meeting transcripts."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def extract(
        self, meeting_title: str, transcript: str
    ) -> list[ExtractedActionItem]:
        """Extract action items from a meeting transcript.

        For long transcripts, processes in chunks and combines results.

        Args:
            meeting_title: Title of the meeting
            transcript: Full transcript text

        Returns:
            List of extracted action items
        """
        # Chunk size for processing (leave room for prompt overhead)
        chunk_size = 5000
        overlap = 500  # Overlap to avoid cutting off action items mid-sentence

        if len(transcript) <= chunk_size:
            # Short transcript - process directly
            return await self._extract_from_chunk(meeting_title, transcript)

        # Long transcript - process in chunks
        logger.info(f"Long transcript ({len(transcript)} chars), processing in chunks")
        all_items = []
        chunks = self._split_into_chunks(transcript, chunk_size, overlap)

        for i, chunk in enumerate(chunks):
            logger.debug(f"Processing chunk {i+1}/{len(chunks)}")
            try:
                items = await self._extract_from_chunk(meeting_title, chunk, chunk_num=i+1, total_chunks=len(chunks))
                all_items.extend(items)
            except LLMError as e:
                logger.warning(f"Failed to process chunk {i+1}: {e}")
                continue

        # Deduplicate similar action items
        unique_items = self._deduplicate_items(all_items)
        logger.info(f"Extracted {len(unique_items)} unique action items from {len(chunks)} chunks")
        return unique_items

    def _split_into_chunks(self, text: str, chunk_size: int, overlap: int) -> list[str]:
        """Split text into overlapping chunks, trying to break at sentence boundaries."""
        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size

            if end >= len(text):
                chunks.append(text[start:])
                break

            # Try to find a sentence boundary near the end
            search_start = max(end - 200, start)
            last_period = text.rfind('. ', search_start, end)
            last_newline = text.rfind('\n', search_start, end)
            break_point = max(last_period, last_newline)

            if break_point > search_start:
                end = break_point + 1

            chunks.append(text[start:end])
            start = end - overlap

        return chunks

    async def _extract_from_chunk(
        self, meeting_title: str, transcript: str, chunk_num: int = 1, total_chunks: int = 1
    ) -> list[ExtractedActionItem]:
        """Extract action items from a single chunk of transcript."""
        chunk_note = ""
        if total_chunks > 1:
            chunk_note = f" (Part {chunk_num} of {total_chunks})"

        prompt = f"""You are a helpful assistant. Analyze this meeting transcript and extract action items.

Meeting: {meeting_title}{chunk_note}

TRANSCRIPT:
{transcript}

Return ONLY a JSON array of action items. Each item should have these fields:
- title: brief task description (required)
- description: details about what needs to be done
- assignee: person responsible (or null if unknown)
- context: relevant quote from the transcript

Only include clear actionable tasks and commitments. Return [] if no action items.

Example format: [{{"title": "Send report", "assignee": "John", "description": "Send weekly report", "context": "John said he would send the report"}}]

JSON array of action items:"""

        try:
            response = await self.llm.complete(prompt, temperature=0.1)
            return self._parse_response(response)
        except LLMError as e:
            logger.error(f"Failed to extract action items: {e}")
            raise

    def _deduplicate_items(self, items: list[ExtractedActionItem]) -> list[ExtractedActionItem]:
        """Remove duplicate action items based on similar titles."""
        if not items:
            return []

        unique = []
        seen_titles = set()

        for item in items:
            # Normalize title for comparison
            normalized = item.title.lower().strip()
            # Remove common words for better matching
            key_words = set(normalized.split()) - {'the', 'a', 'an', 'to', 'for', 'with', 'and', 'or'}
            key = frozenset(key_words)

            # Check if we've seen a very similar title
            is_duplicate = False
            for seen in seen_titles:
                if len(key & seen) >= min(len(key), len(seen)) * 0.7:  # 70% word overlap
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique.append(item)
                seen_titles.add(key)

        return unique

    def _parse_response(self, response: str) -> list[ExtractedActionItem]:
        """Parse LLM response into action items."""
        # Try to extract JSON from the response
        json_str = self._extract_json(response)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response was: {response}")
            return []

        if not isinstance(data, list):
            logger.error("LLM response is not a JSON array")
            return []

        items = []
        for item in data:
            if not isinstance(item, dict):
                continue

            title = item.get("title", "").strip()
            if not title:
                continue

            items.append(
                ExtractedActionItem(
                    title=title[:500],  # Limit title length
                    description=item.get("description", "").strip(),
                    assignee=item.get("assignee"),
                    context=item.get("context", "").strip(),
                )
            )

        logger.info(f"Extracted {len(items)} action items")
        return items

    def _extract_json(self, text: str) -> str:
        """Extract JSON array from text that may contain other content."""
        # First try: the whole response is valid JSON
        text = text.strip()
        if text.startswith("[") and text.endswith("]"):
            return text

        # Second try: find JSON in markdown code block
        code_block_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if code_block_match:
            return code_block_match.group(1)

        # Third try: find any JSON array in the text
        array_match = re.search(r"\[.*\]", text, re.DOTALL)
        if array_match:
            return array_match.group(0)

        # Last resort: return the original text
        return text
