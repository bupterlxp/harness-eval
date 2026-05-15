"""
domain/prompts.py - LLM prompts for element location and data extraction.

Provides prompt templates for:
- Element location by semantic description
- Data extraction from page content
- Report generation
"""

from typing import Any


class PromptTemplates:
    """
    Prompt templates for LLM-assisted browser operations.

    Uses OpenAI-compatible chat format.
    """

    @staticmethod
    def locate_element(
        page_summary: str,
        element_description: str,
        available_elements: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """
        Generate prompt for locating an element by description.

        Returns messages in OpenAI chat format.
        """
        elements_text = "\n".join([
            f"- {e.get('selector')}: {e.get('tag')}[{e.get('type', '')}] "
            f"text='{e.get('text', '')}' placeholder='{e.get('placeholder', '')}'"
            for e in available_elements[:30]
        ])

        return [
            {
                "role": "system",
                "content": """You are a browser automation assistant. Given a page state and
available elements, identify the best CSS selector for the described element.

Respond with ONLY the selector, nothing else. If no matching element is found, respond with "NOT_FOUND".

Prefer selectors in this order:
1. #id selectors (most reliable)
2. [name='...'] for form elements
3. :has-text('...') for buttons/links
4. [placeholder='...'] for inputs"""
            },
            {
                "role": "user",
                "content": f"""Page: {page_summary}

Available elements:
{elements_text}

Find the element: {element_description}

Respond with ONLY the CSS selector."""
            }
        ]

    @staticmethod
    def extract_data(
        page_content: str,
        data_schema: dict[str, str],
    ) -> list[dict[str, str]]:
        """
        Generate prompt for extracting structured data from page content.

        Args:
            page_content: Text content from the page
            data_schema: Dict mapping field names to descriptions

        Returns messages in OpenAI chat format.
        """
        schema_text = "\n".join([
            f"- {field}: {desc}" for field, desc in data_schema.items()
        ])

        return [
            {
                "role": "system",
                "content": """You are a data extraction assistant. Given page content and a schema,
extract the requested data fields.

Respond with valid JSON containing only the requested fields.
If a field cannot be found, use null as the value.
Numbers should be actual numbers, not strings."""
            },
            {
                "role": "user",
                "content": f"""Page content:
{page_content[:3000]}

Extract these fields:
{schema_text}

Respond with ONLY valid JSON."""
            }
        ]

    @staticmethod
    def decide_action(
        page_summary: str,
        task_description: str,
        available_actions: list[str],
        context: str,
    ) -> list[dict[str, str]]:
        """
        Generate prompt for deciding the next action.

        Returns messages in OpenAI chat format.
        """
        actions_text = "\n".join([f"- {action}" for action in available_actions])

        return [
            {
                "role": "system",
                "content": """You are a browser automation agent. Given the current page state,
task description, and available actions, decide the next action to take.

Respond with a JSON object containing:
- action: The action name from the available list
- params: Object with any required parameters
- reasoning: Brief explanation of why this action (1 sentence)"""
            },
            {
                "role": "user",
                "content": f"""Current page: {page_summary}

Task: {task_description}

Context: {context}

Available actions:
{actions_text}

Respond with ONLY valid JSON."""
            }
        ]

    @staticmethod
    def generate_report(
        extracted_data: dict[str, Any],
        step_summaries: list[dict[str, Any]],
        errors: list[str],
    ) -> list[dict[str, str]]:
        """
        Generate prompt for creating the final execution report.

        Returns messages in OpenAI chat format.
        """
        import json

        data_json = json.dumps(extracted_data, ensure_ascii=False, indent=2)
        steps_json = json.dumps(step_summaries, ensure_ascii=False, indent=2)
        errors_text = "\n".join([f"- {e}" for e in errors]) if errors else "None"

        return [
            {
                "role": "system",
                "content": """You are a report generation assistant. Given execution data,
create a clear, structured summary report.

The report should include:
1. Executive summary (2-3 sentences)
2. Key findings from extracted data
3. Step completion summary
4. Any issues or errors encountered
5. Recommendations if applicable

Use markdown formatting."""
            },
            {
                "role": "user",
                "content": f"""Extracted data:
{data_json}

Step execution:
{steps_json}

Errors:
{errors_text}

Generate a summary report."""
            }
        ]

    @staticmethod
    def fill_form(
        form_fields: list[dict[str, Any]],
        data_to_fill: dict[str, str],
    ) -> list[dict[str, str]]:
        """
        Generate prompt for mapping data to form fields.

        Returns messages in OpenAI chat format.
        """
        import json

        fields_json = json.dumps(form_fields, ensure_ascii=False, indent=2)
        data_json = json.dumps(data_to_fill, ensure_ascii=False, indent=2)

        return [
            {
                "role": "system",
                "content": """You are a form filling assistant. Given form fields and data to fill,
map each data value to the appropriate form field.

Respond with a JSON array of actions:
[
  {"selector": "CSS selector", "action": "fill|select|date", "value": "value to enter"},
  ...
]

For select elements, use the option value, not the display text.
For date inputs, use YYYY-MM-DD format."""
            },
            {
                "role": "user",
                "content": f"""Form fields:
{fields_json}

Data to fill:
{data_json}

Respond with ONLY the JSON array of actions."""
            }
        ]

    @staticmethod
    def handle_error(
        error_message: str,
        page_summary: str,
        last_action: str,
        available_recovery_actions: list[str],
    ) -> list[dict[str, str]]:
        """
        Generate prompt for error recovery decision.

        Returns messages in OpenAI chat format.
        """
        actions_text = "\n".join([f"- {a}" for a in available_recovery_actions])

        return [
            {
                "role": "system",
                "content": """You are an error recovery assistant. Given an error during browser
automation, suggest the best recovery action.

Respond with JSON:
{
  "action": "chosen action",
  "params": {},
  "explanation": "why this recovery action"
}

Common recovery strategies:
- retry: Same action might work on retry
- wait: Page might need more time
- navigate: Go to a known good state
- skip: Move to next step if non-critical
- abort: Stop execution if unrecoverable"""
            },
            {
                "role": "user",
                "content": f"""Error: {error_message}

Last action attempted: {last_action}

Current page: {page_summary}

Available recovery actions:
{actions_text}

Respond with ONLY valid JSON."""
            }
        ]


class LLMClient:
    """
    Simple wrapper for OpenAI-compatible LLM calls.

    Usage:
        client = LLMClient(openai_client, "model-name")
        response = await client.complete(messages)
    """

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1000,
    ) -> str:
        """
        Send completion request and return response text.

        Args:
            messages: Chat messages in OpenAI format
            temperature: Sampling temperature (0 = deterministic)
            max_tokens: Maximum response length

        Returns:
            The assistant's response text
        """
        import asyncio

        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )

        return response.choices[0].message.content

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
    ) -> dict[str, Any] | list[Any]:
        """
        Send completion request and parse JSON response.

        Returns parsed JSON object or raises ValueError if invalid.
        """
        import json

        response = await self.complete(messages, temperature)

        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]

        return json.loads(response.strip())
