"""Tests for Granola cache parser."""

import json
from pathlib import Path

import pytest

from granola_bridge.services.granola_parser import GranolaParser, GranolaMeeting


class TestGranolaParser:
    def test_parse_valid_cache(self, sample_granola_cache):
        """Test parsing a valid Granola cache file."""
        parser = GranolaParser(sample_granola_cache)
        meetings = parser.parse()

        assert len(meetings) == 1
        meeting = meetings[0]
        assert meeting.granola_id == "meeting-123"
        assert meeting.title == "Weekly Standup"
        assert "Sarah" in meeting.transcript
        assert len(meeting.participants) == 3

    def test_parse_missing_file(self, temp_dir):
        """Test parsing when cache file doesn't exist."""
        parser = GranolaParser(temp_dir / "nonexistent.json")
        meetings = parser.parse()
        assert meetings == []

    def test_parse_invalid_json(self, temp_dir):
        """Test parsing invalid JSON."""
        cache_path = temp_dir / "invalid.json"
        cache_path.write_text("not valid json")

        parser = GranolaParser(cache_path)
        meetings = parser.parse()
        assert meetings == []

    def test_get_new_meetings(self, sample_granola_cache):
        """Test filtering out already-processed meetings."""
        parser = GranolaParser(sample_granola_cache)

        # First call should return the meeting
        new = parser.get_new_meetings(set())
        assert len(new) == 1

        # Second call with known ID should return empty
        known_ids = {"meeting-123"}
        new = parser.get_new_meetings(known_ids)
        assert len(new) == 0

    def test_has_changes(self, sample_granola_cache):
        """Test change detection."""
        parser = GranolaParser(sample_granola_cache)

        # Should detect changes on first check
        assert parser.has_changes() is True

        # Parse to update last_modified
        parser.parse()

        # No changes without file modification
        assert parser.has_changes() is False

    def test_parse_various_transcript_formats(self, temp_dir):
        """Test parsing different transcript field formats."""
        # Test with 'text' field
        cache_data = {
            "meetings": [
                {
                    "id": "m1",
                    "title": "Test",
                    "text": "Direct text content",
                }
            ]
        }
        cache_path = temp_dir / "cache.json"
        cache_path.write_text(json.dumps(cache_data))

        parser = GranolaParser(cache_path)
        meetings = parser.parse()
        assert len(meetings) == 1
        assert meetings[0].transcript == "Direct text content"

    def test_parse_segments_format(self, temp_dir):
        """Test parsing segmented transcript format."""
        cache_data = {
            "meetings": [
                {
                    "id": "m1",
                    "title": "Test",
                    "segments": [
                        {"speaker": "Alice", "text": "Hello"},
                        {"speaker": "Bob", "text": "Hi there"},
                    ],
                }
            ]
        }
        cache_path = temp_dir / "cache.json"
        cache_path.write_text(json.dumps(cache_data))

        parser = GranolaParser(cache_path)
        meetings = parser.parse()
        assert len(meetings) == 1
        assert "Alice: Hello" in meetings[0].transcript
        assert "Bob: Hi there" in meetings[0].transcript

    def test_skip_meeting_without_transcript(self, temp_dir):
        """Test that meetings without transcripts are skipped."""
        cache_data = {
            "meetings": [
                {
                    "id": "m1",
                    "title": "No Transcript Meeting",
                    # No transcript field
                }
            ]
        }
        cache_path = temp_dir / "cache.json"
        cache_path.write_text(json.dumps(cache_data))

        parser = GranolaParser(cache_path)
        meetings = parser.parse()
        assert len(meetings) == 0
