"""Tests for action item extraction."""

import json

import pytest

from granola_bridge.services.action_extractor import ActionExtractor, ExtractedActionItem


class MockLLMClient:
    """Mock LLM client for testing."""

    def __init__(self, response: str):
        self.response = response
        self.calls = []

    async def complete(self, prompt: str, system_prompt: str = None, **kwargs):
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt})
        return self.response


class SequentialMockLLMClient:
    """Mock LLM client that returns different responses for sequential calls."""

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls = []
        self._call_index = 0

    async def complete(self, prompt: str, system_prompt: str = None, **kwargs):
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt})
        response = self.responses[min(self._call_index, len(self.responses) - 1)]
        self._call_index += 1
        return response


class TestActionExtractor:
    @pytest.mark.asyncio
    async def test_extract_valid_json(self):
        """Test extraction with valid JSON response."""
        response = """[
            {
                "title": "Schedule meeting with design team",
                "description": "Set up a 30-minute meeting to review mockups",
                "assignee": "Sarah",
                "context": "Can you also schedule a meeting with the design team?",
                "weight": 5
            },
            {
                "title": "Update documentation",
                "description": "Update docs after database migration",
                "assignee": "Mike",
                "context": "can you also update the documentation once that's done?",
                "weight": 4
            }
        ]"""

        llm = MockLLMClient(response)
        extractor = ActionExtractor(llm)

        items = await extractor.extract("Weekly Standup", "Test transcript")

        assert len(items) == 2
        assert items[0].title == "Schedule meeting with design team"
        assert items[0].assignee == "Sarah"
        assert items[1].title == "Update documentation"
        assert items[1].assignee == "Mike"

    @pytest.mark.asyncio
    async def test_extract_json_in_code_block(self):
        """Test extraction when JSON is wrapped in code block."""
        response = """Here are the action items I found:

```json
[
    {
        "title": "Submit timesheets",
        "description": "Submit by Friday",
        "assignee": null,
        "context": "Remember to submit your timesheets by Friday",
        "weight": 5
    }
]
```

Let me know if you need anything else!"""

        llm = MockLLMClient(response)
        extractor = ActionExtractor(llm)

        items = await extractor.extract("Test", "Test transcript")

        assert len(items) == 1
        assert items[0].title == "Submit timesheets"
        assert items[0].assignee is None

    @pytest.mark.asyncio
    async def test_extract_empty_array(self):
        """Test extraction when no action items found."""
        response = "[]"

        llm = MockLLMClient(response)
        extractor = ActionExtractor(llm)

        items = await extractor.extract("Test", "Just a casual chat")

        assert len(items) == 0

    @pytest.mark.asyncio
    async def test_extract_invalid_json(self):
        """Test handling of invalid JSON response."""
        response = "Sorry, I couldn't parse the transcript properly."

        llm = MockLLMClient(response)
        extractor = ActionExtractor(llm)

        items = await extractor.extract("Test", "Test transcript")

        assert len(items) == 0

    @pytest.mark.asyncio
    async def test_extract_truncates_long_titles(self):
        """Test that very long titles are truncated."""
        long_title = "A" * 600
        response = f"""[
            {{
                "title": "{long_title}",
                "description": "Test",
                "assignee": null,
                "context": "Test",
                "weight": 5
            }}
        ]"""

        llm = MockLLMClient(response)
        extractor = ActionExtractor(llm)

        items = await extractor.extract("Test", "Test transcript")

        assert len(items) == 1
        assert len(items[0].title) == 500

    @pytest.mark.asyncio
    async def test_extract_skips_items_without_title(self):
        """Test that items without titles are skipped."""
        response = """[
            {
                "title": "",
                "description": "No title here",
                "assignee": null,
                "context": "Test",
                "weight": 5
            },
            {
                "title": "Valid item",
                "description": "This one has a title",
                "assignee": null,
                "context": "Test",
                "weight": 5
            }
        ]"""

        llm = MockLLMClient(response)
        extractor = ActionExtractor(llm)

        items = await extractor.extract("Test", "Test transcript")

        assert len(items) == 1
        assert items[0].title == "Valid item"

    @pytest.mark.asyncio
    async def test_extract_filters_by_weight(self):
        """Test that low-weight items are filtered out (min_weight=4)."""
        response = """[
            {"title": "Critical task", "description": "Must do", "assignee": "Alice", "context": "I will do this", "weight": 5},
            {"title": "Important task", "description": "Should do", "assignee": "Bob", "context": "I'll handle it", "weight": 4},
            {"title": "Moderate task", "description": "Might do", "assignee": "Charlie", "context": "We could", "weight": 3},
            {"title": "Not a task", "description": "Just mentioned", "assignee": null, "context": "Someone said", "weight": 1}
        ]"""

        llm = MockLLMClient(response)
        extractor = ActionExtractor(llm)

        items = await extractor.extract("Test", "Test transcript")

        # Only weight >= 4 should pass (new default)
        assert len(items) == 2
        assert items[0].title == "Critical task"
        assert items[0].weight == 5
        assert items[1].title == "Important task"
        assert items[1].weight == 4

    @pytest.mark.asyncio
    async def test_extract_caps_at_max_items(self):
        """Test that results are capped at max items (5)."""
        # Create 8 items, all with weight 5
        items_json = [
            {"title": f"Task {i}", "description": f"Do thing {i}", "assignee": "Person", "context": "I will", "weight": 5}
            for i in range(8)
        ]
        response = json.dumps(items_json)

        llm = MockLLMClient(response)
        extractor = ActionExtractor(llm)

        items = await extractor.extract("Test", "Test transcript")

        # Should be capped at 5 (new default)
        assert len(items) == 5

    @pytest.mark.asyncio
    async def test_extract_sorts_by_weight(self):
        """Test that results are sorted by weight descending."""
        response = """[
            {"title": "Medium priority", "description": "Do soon", "assignee": "Alice", "context": "Test", "weight": 4},
            {"title": "High priority", "description": "Do now", "assignee": "Bob", "context": "Test", "weight": 5},
            {"title": "Also high", "description": "Do now too", "assignee": "Charlie", "context": "Test", "weight": 5}
        ]"""

        llm = MockLLMClient(response)
        extractor = ActionExtractor(llm)

        items = await extractor.extract("Test", "Test transcript")

        assert len(items) == 3
        assert items[0].weight == 5
        assert items[1].weight == 5
        assert items[2].weight == 4

    @pytest.mark.asyncio
    async def test_consolidation_for_long_transcripts(self):
        """Test that multi-chunk transcripts get a consolidation pass."""
        # Create a transcript that will be split into chunks (> 5000 chars)
        long_transcript = "Speaker A: We need to do many things. " * 200  # ~7800 chars

        # Chunk extraction returns many items
        chunk_response = json.dumps([
            {"title": f"Task {i}", "description": f"Do {i}", "assignee": "Person", "context": "I will", "weight": 5}
            for i in range(6)
        ])

        # Consolidation returns fewer items
        consolidated_response = json.dumps([
            {"title": "Task 0", "description": "Do 0", "assignee": "Person", "context": "I will", "weight": 5},
            {"title": "Task 1", "description": "Do 1", "assignee": "Person", "context": "I will", "weight": 5},
            {"title": "Task 2", "description": "Do 2", "assignee": "Person", "context": "I will", "weight": 4},
        ])

        # Use sequential mock: chunk calls first, then consolidation
        llm = SequentialMockLLMClient([chunk_response, chunk_response, consolidated_response])
        extractor = ActionExtractor(llm)

        items = await extractor.extract("Long Meeting", long_transcript)

        # Should have gone through consolidation
        assert len(llm.calls) >= 3  # At least 2 chunk calls + 1 consolidation
        # Consolidation prompt should mention "candidate action items"
        last_call = llm.calls[-1]["prompt"]
        assert "candidate action items" in last_call.lower() or "Candidate items" in last_call

    @pytest.mark.asyncio
    async def test_consolidation_skipped_when_few_items(self):
        """Test that consolidation is skipped when <= 5 unique items."""
        long_transcript = "Speaker A: We need to do things. " * 200

        # Return only 3 items per chunk, but they're duplicates
        chunk_response = json.dumps([
            {"title": "Task A", "description": "Do A", "assignee": "Person", "context": "I will", "weight": 5},
            {"title": "Task B", "description": "Do B", "assignee": "Person", "context": "I will", "weight": 4},
        ])

        llm = MockLLMClient(chunk_response)
        extractor = ActionExtractor(llm)

        items = await extractor.extract("Short Items Meeting", long_transcript)

        # With dedup, likely <= 5 unique items, so no consolidation call
        # All calls should be chunk extraction calls (contain "TRANSCRIPT:")
        for call in llm.calls:
            assert "TRANSCRIPT:" in call["prompt"]

    @pytest.mark.asyncio
    async def test_prompt_contains_meeting_type_guidance(self):
        """Test that extraction prompt includes meeting type classification."""
        response = "[]"
        llm = MockLLMClient(response)
        extractor = ActionExtractor(llm)

        await extractor.extract("Sales Call with Acme", "Test transcript")

        prompt = llm.calls[0]["prompt"]
        assert "SALES_CALL" in prompt
        assert "PROJECT_UPDATE" in prompt
        assert "STRATEGY" in prompt
        assert "CATCH_UP" in prompt

    @pytest.mark.asyncio
    async def test_prompt_excludes_noise(self):
        """Test that extraction prompt has explicit noise exclusion list."""
        response = "[]"
        llm = MockLLMClient(response)
        extractor = ActionExtractor(llm)

        await extractor.extract("Test", "Test transcript")

        prompt = llm.calls[0]["prompt"]
        assert "Do NOT include" in prompt
        assert "noodle on" in prompt
        assert "explore" in prompt
        assert "concrete commitments" in prompt or "concrete commitments and deliverables" in prompt
