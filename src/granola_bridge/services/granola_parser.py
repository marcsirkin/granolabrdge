"""Parser for Granola's cache file (v3 and v4 formats)."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GranolaMeeting:
    """Parsed meeting from Granola cache."""

    granola_id: str
    title: str
    transcript: str
    meeting_date: Optional[datetime]
    participants: list[str]
    meeting_end_count: int = 0  # 0 = in progress, 1+ = ended
    raw_segments: list[dict] | None = None  # structured speaker turns when available


class GranolaParser:
    """Parse and extract meetings from Granola's cache file.

    Supported formats:
    - v3: {"cache": "<JSON_STRING>"}  where JSON_STRING contains {"state": {...}}
    - v4: {"cache": {"state": {...}, "version": ...}}

    In both cases, state.documents is a dict of meeting docs keyed by ID,
    and state.transcripts is a dict of transcript segment lists keyed by doc ID.
    """

    def __init__(self, cache_path: Path):
        self.cache_path = self._resolve_cache_path(cache_path)
        self._last_modified: Optional[float] = None
        self._known_ids: set[str] = set()

    @staticmethod
    def _resolve_cache_path(configured: Path) -> Path:
        """Use configured path if it exists; otherwise find the highest-versioned cache-vN.json."""
        if configured.exists():
            return configured
        granola_dir = configured.parent
        candidates = sorted(granola_dir.glob("cache-v*.json"), reverse=True)
        if candidates:
            logger.info(f"Configured cache not found ({configured.name}); using {candidates[0].name}")
            return candidates[0]
        return configured  # fall through; original missing-file warning still fires

    def has_changes(self) -> bool:
        """Check if the cache file has been modified."""
        if not self.cache_path.exists():
            return False

        current_mtime = self.cache_path.stat().st_mtime
        if self._last_modified is None or current_mtime > self._last_modified:
            return True
        return False

    def parse(self) -> list[GranolaMeeting]:
        """Parse all meetings from the cache file."""
        if not self.cache_path.exists():
            logger.warning(f"Granola cache not found: {self.cache_path}")
            return []

        try:
            with open(self.cache_path, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Granola cache: {e}")
            return []

        self._last_modified = self.cache_path.stat().st_mtime

        # Handle Granola's double-encoded JSON structure
        state = self._extract_state(data)
        if state is None:
            return []

        documents = state.get("documents", {})
        transcripts = state.get("transcripts", {})

        if not isinstance(documents, dict):
            logger.error("documents is not a dict")
            return []

        meetings = []
        for doc_id, doc in documents.items():
            meeting = self._parse_document(doc, transcripts)
            if meeting:
                meetings.append(meeting)

        logger.info(f"Parsed {len(meetings)} meetings from Granola cache")
        return meetings

    def _extract_state(self, data: dict) -> Optional[dict]:
        """Extract the state object from Granola's cache structure.

        v3: {"cache": "<JSON_STRING>"}  where JSON_STRING contains {"state": {...}}
        v4: {"cache": {"state": {...}, "version": ...}}
        """
        if isinstance(data, dict) and "cache" in data:
            cache_val = data["cache"]
            if isinstance(cache_val, str):
                # v3: double-encoded JSON string
                try:
                    inner = json.loads(cache_val)
                    return inner.get("state", {})
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse inner cache JSON: {e}")
                    return None
            elif isinstance(cache_val, dict):
                # v4: cache is already a parsed dict
                return cache_val.get("state", {})

        # Fallback: maybe it's already unwrapped
        if isinstance(data, dict) and "state" in data:
            return data["state"]

        logger.error("Could not find state in Granola cache")
        return None

    def get_new_meetings(self, known_ids: set[str]) -> list[GranolaMeeting]:
        """Get only meetings that haven't been processed yet.

        Args:
            known_ids: Set of granola_ids that have already been processed

        Returns:
            List of new meetings not in known_ids
        """
        all_meetings = self.parse()
        new_meetings = [m for m in all_meetings if m.granola_id not in known_ids]

        if new_meetings:
            logger.info(f"Found {len(new_meetings)} new meetings")

        return new_meetings

    def get_meeting_by_id(self, granola_id: str) -> Optional[GranolaMeeting]:
        """Fetch a specific meeting from the cache by its Granola ID.

        Args:
            granola_id: The Granola document ID to look up

        Returns:
            GranolaMeeting if found, None otherwise
        """
        all_meetings = self.parse()
        for meeting in all_meetings:
            if meeting.granola_id == granola_id:
                return meeting
        return None

    def get_structured_segments(self, doc_id: str, raw_segments: list) -> list[dict]:
        """Group adjacent transcript segments from the same source into speaker turns.

        Args:
            doc_id: Document ID (for logging)
            raw_segments: List of segment dicts from Granola's transcript data

        Returns:
            List of dicts with speaker, source, text, start_timestamp, end_timestamp, segment_index
        """
        if not raw_segments:
            return []

        # Sort by start_timestamp
        try:
            sorted_segs = sorted(
                raw_segments,
                key=lambda s: s.get("start_timestamp", "") if isinstance(s, dict) else "",
            )
        except Exception:
            sorted_segs = raw_segments

        turns: list[dict] = []
        current_turn: dict | None = None

        for seg in sorted_segs:
            if not isinstance(seg, dict):
                continue
            text = seg.get("text", "").strip()
            if not text:
                continue

            source = seg.get("source", "")
            speaker = seg.get("speaker", "")

            if current_turn and current_turn["source"] == source and current_turn["speaker"] == speaker:
                # Same speaker/source -- merge into current turn
                current_turn["text"] += " " + text
                current_turn["end_timestamp"] = seg.get("end_timestamp", current_turn["end_timestamp"])
            else:
                # New turn
                if current_turn:
                    turns.append(current_turn)
                current_turn = {
                    "speaker": speaker,
                    "source": source,
                    "text": text,
                    "start_timestamp": seg.get("start_timestamp", ""),
                    "end_timestamp": seg.get("end_timestamp", ""),
                    "segment_index": len(turns),
                }

        if current_turn:
            turns.append(current_turn)

        # Fix up segment_index after appending
        for i, turn in enumerate(turns):
            turn["segment_index"] = i

        logger.debug(f"Document {doc_id}: grouped {len(raw_segments)} segments into {len(turns)} speaker turns")
        return turns

    def _parse_document(self, doc: dict, transcripts: dict) -> Optional[GranolaMeeting]:
        """Parse a single document into a meeting."""
        try:
            doc_id = doc.get("id")
            if not doc_id:
                return None

            title = doc.get("title") or "Untitled Meeting"

            # Get transcript - first try the transcripts dict, then fall back to notes
            transcript = self._get_transcript(doc_id, doc, transcripts)
            if not transcript or len(transcript.strip()) < 20:
                logger.debug(f"Document {doc_id} has no/minimal transcript, skipping")
                return None

            # Parse date
            meeting_date = self._parse_date(doc.get("created_at"))

            # Extract participants from people field
            participants = self._extract_participants(doc.get("people", []))

            # Get meeting_end_count (0 = in progress, 1+ = ended)
            meeting_end_count = doc.get("meeting_end_count", 0)
            if not isinstance(meeting_end_count, int):
                meeting_end_count = 0

            # Extract structured segments if raw transcript data is available
            raw_segments = None
            if doc_id in transcripts:
                segs = transcripts[doc_id]
                if isinstance(segs, list) and segs:
                    raw_segments = self.get_structured_segments(doc_id, segs)

            return GranolaMeeting(
                granola_id=str(doc_id),
                title=title,
                transcript=transcript,
                meeting_date=meeting_date,
                participants=participants,
                meeting_end_count=meeting_end_count,
                raw_segments=raw_segments,
            )

        except Exception as e:
            logger.error(f"Failed to parse document: {e}")
            return None

    def _get_transcript(self, doc_id: str, doc: dict, transcripts: dict) -> Optional[str]:
        """Get transcript text for a document."""
        # First try: transcript segments from transcripts dict
        if doc_id in transcripts:
            segments = transcripts[doc_id]
            if isinstance(segments, list) and segments:
                transcript = self._join_transcript_segments(segments)
                if transcript:
                    return transcript
                else:
                    logger.warning(
                        f"Document {doc_id}: {len(segments)} transcript segments produced empty result, "
                        f"falling back to notes"
                    )

        # Second try: notes_plain or notes_markdown from document
        notes = doc.get("notes_plain") or doc.get("notes_markdown") or ""
        if notes.strip():
            return notes

        # Third try: summary
        summary = doc.get("summary") or ""
        if summary.strip():
            return summary

        return None

    def _join_transcript_segments(self, segments: list) -> str:
        """Join transcript segments into a single string."""
        # Debug: log segment format info to diagnose join failures
        if segments:
            first = segments[0]
            segment_type = type(first).__name__
            sample_keys = list(first.keys())[:5] if isinstance(first, dict) else None
            logger.debug(
                f"Joining {len(segments)} segments: type={segment_type}, "
                f"sample_keys={sample_keys}"
            )

        # Sort by start_timestamp if available
        try:
            sorted_segments = sorted(
                segments,
                key=lambda s: s.get("start_timestamp", "") if isinstance(s, dict) else ""
            )
        except Exception as e:
            logger.warning(f"Failed to sort transcript segments: {e}")
            sorted_segments = segments

        texts = []
        for segment in sorted_segments:
            if isinstance(segment, str):
                texts.append(segment)
            elif isinstance(segment, dict):
                text = segment.get("text", "")
                if text:
                    # Mark source if it's from system audio vs microphone
                    source = segment.get("source", "")
                    if source == "system_audio":
                        texts.append(f"[Remote] {text}")
                    else:
                        texts.append(text)

        return " ".join(texts)

    def _parse_date(self, value) -> Optional[datetime]:
        """Parse a date value."""
        if not value:
            return None

        try:
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(value)
            if isinstance(value, str):
                # Try ISO format variations
                for fmt in [
                    "%Y-%m-%dT%H:%M:%S.%fZ",
                    "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d",
                ]:
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue
                # Try fromisoformat as fallback
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00"))
                except Exception:
                    pass
        except Exception:
            pass

        return None

    def _extract_participants(self, people: list) -> list[str]:
        """Extract participant names from people list."""
        participants = []

        if not isinstance(people, list):
            return participants

        for person in people:
            if isinstance(person, str):
                participants.append(person)
            elif isinstance(person, dict):
                name = (
                    person.get("name")
                    or person.get("displayName")
                    or person.get("email", "").split("@")[0]
                )
                if name:
                    participants.append(name)

        return participants
