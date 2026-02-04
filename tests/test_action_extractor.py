"""Tests for action item extraction."""

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


class TestActionExtractor:
    @pytest.mark.asyncio
    async def test_extract_valid_json(self):
        """Test extraction with valid JSON response."""
        response = """[
            {
                "title": "Schedule meeting with design team",
                "description": "Set up a 30-minute meeting to review mockups",
                "assignee": "Sarah",
                "context": "Can you also schedule a meeting with the design team?"
            },
            {
                "title": "Update documentation",
                "description": "Update docs after database migration",
                "assignee": "Mike",
                "context": "can you also update the documentation once that's done?"
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
        "context": "Remember to submit your timesheets by Friday"
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
                "context": "Test"
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
                "context": "Test"
            },
            {
                "title": "Valid item",
                "description": "This one has a title",
                "assignee": null,
                "context": "Test"
            }
        ]"""

        llm = MockLLMClient(response)
        extractor = ActionExtractor(llm)

        items = await extractor.extract("Test", "Test transcript")

        assert len(items) == 1
        assert items[0].title == "Valid item"
