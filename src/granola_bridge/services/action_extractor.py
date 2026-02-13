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

MEETING_TYPE_GUIDANCE = """First, classify this meeting as one of:
- SALES_CALL: Prospect/client call focused on selling or partnership
- PROJECT_UPDATE: Status meeting, standup, or project review
- STRATEGY: Planning, brainstorming, or strategic discussion
- CATCH_UP: 1:1 or informal check-in

Then apply the appropriate filter:
- SALES_CALL: Focus on follow-up commitments (send proposal, schedule demo, share pricing).
- PROJECT_UPDATE: Focus on deliverables with owners and deadlines.
- STRATEGY: Focus on decisions made and assigned next steps, NOT ideas discussed.
- CATCH_UP: Focus only on explicit commitments, NOT topics discussed."""

CONSOLIDATION_PROMPT_TEMPLATE = """Here are candidate action items extracted from the meeting "{meeting_title}".

Select only the 3-5 items that represent real, concrete commitments or deliverables. Remove anything vague, exploratory, discussion-only, or redundant.

Candidate items:
{items_json}

Rules:
- Keep ONLY items where someone explicitly committed to doing something specific
- Remove vague intentions ("look into", "think about", "explore", "noodle on")
- Remove status updates, questions, and topics merely discussed
- Remove duplicates, keeping the most specific version
- Return 3-5 items maximum. Fewer is better if the meeting had few real commitments.
- Preserve the original fields (title, description, assignee, context, weight)
- Reassign weights based on the full meeting context

Return ONLY a JSON array. Return [] if no items qualify.

JSON array:"""


@dataclass
class ExtractedActionItem:
    """An action item extracted from a transcript."""

    title: str
    description: str
    assignee: Optional[str]
    context: str
    weight: int = 3  # 1-5 scale: 5=critical, 3=moderate, 1=low priority


class ActionExtractor:
    """Extract action items from meeting transcripts."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def extract(
        self, meeting_title: str, transcript: str
    ) -> list[ExtractedActionItem]:
        """Extract action items from a meeting transcript.

        For long transcripts, processes in chunks, then consolidates results
        with a second LLM pass to select the top items.

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
            items = await self._extract_from_chunk(meeting_title, transcript)
            return self._filter_by_importance(items)

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

        # Consolidation pass: LLM picks the top 3-5 from all candidates
        consolidated = await self._consolidate_items(meeting_title, unique_items)

        # Final filter by weight and cap
        return self._filter_by_importance(consolidated)

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

        prompt = f"""Extract only concrete commitments and deliverables from this meeting. Be selective — most meetings have only 3-5 real action items.

{MEETING_TYPE_GUIDANCE}

Meeting: {meeting_title}{chunk_note}

TRANSCRIPT:
{transcript}

For each action item, assign a weight (1-5):
- 5 = CRITICAL: Explicit commitment to a deliverable, clear owner, mentioned in wrap-up or explicitly called out as "action item"
- 4 = IMPORTANT: Clear commitment with owner, concrete task with specific outcome
- 3 = MODERATE: Likely action item but slightly vague or uncertain commitment
- 2 = WEAK: Mentioned as possibility, soft commitment, no clear owner
- 1 = NOT REALLY: Suggestion without buy-in, question, status update, or "think about/look into"

Do NOT include:
- Topics merely discussed or mentioned
- Questions asked during the meeting
- Vague intentions ("look into", "think about", "explore", "noodle on", "consider")
- Status updates or information shared
- Things referenced but not committed to
- TV shows, articles, or media recommendations

Return ONLY a JSON array with 3-5 items maximum. Each item needs:
- title: brief task description (required)
- description: what specifically needs to be done
- assignee: person responsible (null if unclear)
- context: the exact quote showing commitment
- weight: importance score 1-5 (required)

Return [] if no concrete commitments found.

Example: [{{"title": "Send Q4 budget report to finance", "assignee": "Sarah", "description": "Email the Q4 budget report to finance team by Friday", "context": "Sarah said: I'll send the Q4 budget report to finance by end of week", "weight": 5}}]

JSON array:"""

        try:
            response = await self.llm.complete(prompt, temperature=0.1)
            return self._parse_response(response)
        except LLMError as e:
            logger.error(f"Failed to extract action items: {e}")
            raise

    async def _consolidate_items(
        self, meeting_title: str, items: list[ExtractedActionItem]
    ) -> list[ExtractedActionItem]:
        """Send collected items back to LLM to pick the top 3-5.

        This is the second pass for long/multi-chunk transcripts. The LLM
        sees all candidates at once and selects only the most concrete.

        Args:
            meeting_title: Title of the meeting
            items: All deduplicated items from chunk passes

        Returns:
            Consolidated list of top action items
        """
        if len(items) <= 5:
            # Already within target range, skip consolidation
            return items

        # Serialize items for the prompt
        items_data = [
            {
                "title": item.title,
                "description": item.description,
                "assignee": item.assignee,
                "context": item.context,
                "weight": item.weight,
            }
            for item in items
        ]
        items_json = json.dumps(items_data, indent=2)

        prompt = CONSOLIDATION_PROMPT_TEMPLATE.format(
            meeting_title=meeting_title, items_json=items_json
        )

        try:
            response = await self.llm.complete(prompt, temperature=0.1)
            consolidated = self._parse_response(response)
            if consolidated:
                logger.info(
                    f"Consolidation reduced {len(items)} items to {len(consolidated)}"
                )
                return consolidated
            else:
                # LLM returned empty — fall back to original items
                logger.warning("Consolidation returned empty, using original items")
                return items
        except LLMError as e:
            logger.warning(f"Consolidation pass failed, using original items: {e}")
            return items

    def _filter_by_importance(
        self, items: list[ExtractedActionItem], min_weight: int = 4, max_items: int = 5
    ) -> list[ExtractedActionItem]:
        """Filter action items by importance weight and cap the total.

        Args:
            items: List of extracted action items with weights
            min_weight: Minimum weight to include (default 4)
            max_items: Maximum number of items to return (default 5)

        Returns:
            Filtered and sorted list of action items
        """
        if not items:
            return []

        # Filter by minimum weight
        filtered = [item for item in items if item.weight >= min_weight]
        logger.debug(f"Filtered from {len(items)} to {len(filtered)} items (weight >= {min_weight})")

        # Sort by weight descending, then by title for stability
        filtered.sort(key=lambda x: (-x.weight, x.title))

        # Cap at max items
        if len(filtered) > max_items:
            logger.info(f"Capping action items from {len(filtered)} to {max_items}")
            filtered = filtered[:max_items]

        logger.info(f"Final action items: {len(filtered)} (weights: {[i.weight for i in filtered]})")
        return filtered

    def _deduplicate_items(self, items: list[ExtractedActionItem]) -> list[ExtractedActionItem]:
        """Remove duplicate action items based on similar titles, keeping higher-weighted version."""
        if not items:
            return []

        # Sort by weight descending so we see higher-weighted items first
        sorted_items = sorted(items, key=lambda x: -x.weight)

        unique = []
        seen_titles: list[frozenset] = []

        for item in sorted_items:
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
                seen_titles.append(key)

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

            # Parse weight, default to 3 if missing or invalid
            weight = item.get("weight", 3)
            if not isinstance(weight, int) or weight < 1 or weight > 5:
                weight = 3

            items.append(
                ExtractedActionItem(
                    title=title[:500],  # Limit title length
                    description=item.get("description", "").strip(),
                    assignee=item.get("assignee"),
                    context=item.get("context", "").strip(),
                    weight=weight,
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
