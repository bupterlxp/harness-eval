"""Prompt Templates for Research Agent.

Contains all LLM prompts for:
- Question decomposition
- Source evaluation
- Fact extraction
- Section drafting
- Gap analysis
- Cross-validation
"""


class PromptTemplates:
    """Collection of prompt templates for research tasks."""

    @staticmethod
    def web_search_simulation(query: str, max_results: int) -> str:
        """Prompt for simulating web search results."""
        return f"""You are simulating a web search engine. Given the query below, generate {max_results} realistic search results related to academic papers, technical documentation, and authoritative sources.

Query: {query}

Return a JSON array with objects containing:
- "url": A realistic URL (prefer arxiv.org, github.com, official docs)
- "title": The page title
- "content": A 200-300 word excerpt of the page content with factual information

Focus on:
1. Academic papers from arXiv for research topics
2. Official documentation for technical topics
3. Reputable tech blogs for practical insights

Return ONLY the JSON array, no other text.

Example format:
[
  {{
    "url": "https://arxiv.org/abs/2107.03374",
    "title": "Evaluating Large Language Models Trained on Code",
    "content": "We introduce Codex, a GPT language model fine-tuned on publicly available code from GitHub..."
  }}
]"""

    @staticmethod
    def extract_facts(content: str, questions: list[str], sections: list[str]) -> str:
        """Prompt for extracting facts from content."""
        questions_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
        sections_text = ", ".join(sections)

        return f"""Extract key facts from the following content that are relevant to the research questions.

CONTENT:
{content[:5000]}

RESEARCH QUESTIONS:
{questions_text}

TARGET SECTIONS: {sections_text}

For each fact, determine:
1. The specific content/claim
2. The source paragraph it came from
3. Which section it belongs to
4. Which questions it helps answer
5. Confidence level (0-1)

Return a JSON array with objects containing:
- "content": The extracted fact (be specific, include numbers/data when available)
- "source_paragraph": The original text this fact comes from
- "target_section": One of [{sections_text}]
- "related_questions": Array of question indices (0-based)
- "confidence": Float 0-1
- "relevance_score": Float 0-1

Extract 3-8 facts. Return ONLY the JSON array."""

    @staticmethod
    def decompose_questions(topic: str, questions: list[str], sections: list[str]) -> str:
        """Prompt for decomposing questions into search queries."""
        questions_text = "\n".join(f"{i}. {q}" for i, q in enumerate(questions))
        sections_text = "\n".join(f"- {s}" for s in sections)

        return f"""Decompose the following research questions into specific search queries.

TOPIC: {topic}

QUESTIONS:
{questions_text}

TARGET SECTIONS:
{sections_text}

Generate 10-15 search queries that will help gather comprehensive information for the report. Each query should:
1. Be specific enough to return relevant results
2. Target a specific aspect of a question
3. Be mapped to a target section

Return a JSON array with objects containing:
- "query_text": The search query string
- "question_index": Which question this addresses (0-based)
- "target_section": Which section this will inform

Example:
[
  {{
    "query_text": "GPT-4 code generation HumanEval benchmark performance 2024",
    "question_index": 0,
    "target_section": "主流模型对比"
  }}
]

Return ONLY the JSON array."""

    @staticmethod
    def analyze_gap(section: str, evidence: list[dict], questions: list[str]) -> str:
        """Prompt for analyzing information gaps."""
        evidence_text = "\n".join(
            f"- {e.get('content', '')[:200]}"
            for e in evidence
        ) if evidence else "No evidence collected yet."

        questions_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))

        return f"""Analyze the information gaps for the following report section.

SECTION: {section}

CURRENT EVIDENCE:
{evidence_text}

RESEARCH QUESTIONS:
{questions_text}

Identify:
1. What topics are missing or under-covered
2. What additional searches would fill these gaps

Return a JSON object:
{{
  "missing_topics": ["topic1", "topic2", ...],
  "suggested_queries": ["search query 1", "search query 2", ...]
}}

Be specific about what's missing. Return ONLY the JSON object."""

    @staticmethod
    def cross_validate(claim: str, sources: list[dict]) -> str:
        """Prompt for cross-validating a claim."""
        sources_text = "\n\n".join(
            f"SOURCE {i+1} ({s.get('url', 'unknown')}):\n{s.get('content', '')[:500]}"
            for i, s in enumerate(sources)
        )

        return f"""Cross-validate the following claim against the provided sources.

CLAIM: {claim}

SOURCES:
{sources_text}

Determine if the claim is supported, contradicted, or not addressed by each source.

Return a JSON object:
{{
  "is_valid": true/false,
  "supporting_sources": ["url1", "url2"],
  "conflicting_sources": ["url3"],
  "confidence": 0.0-1.0,
  "notes": "Brief explanation"
}}

Return ONLY the JSON object."""

    @staticmethod
    def draft_section(
        section_name: str,
        evidence: list[dict],
        expectations: dict,
    ) -> str:
        """Prompt for drafting a report section."""
        evidence_text = "\n\n".join(
            f"[{e.get('citation_number', '?')}] {e.get('content', '')}\n"
            f"(Source: {e.get('source_title', 'Unknown')})"
            for e in evidence
        ) if evidence else "No evidence available."

        expectations_text = ""
        if expectations:
            if isinstance(expectations, str):
                expectations_text = f"\nEXPECTED CONTENT: {expectations}"
            elif isinstance(expectations, dict):
                expectations_text = f"\nEXPECTED CONTENT: {expectations.get('description', str(expectations))}"

        return f"""Write the "{section_name}" section of a research report.

AVAILABLE EVIDENCE:
{evidence_text}
{expectations_text}

GUIDELINES:
1. Use the evidence provided, citing with [number] format
2. Be factual and objective
3. Present multiple viewpoints where applicable
4. Keep the section focused and well-organized
5. Use clear, academic writing style
6. Include specific data points and numbers from the evidence
7. For comparison sections, use tables where appropriate

Write the section content directly. Do not include the section title (it will be added automatically).
Every factual claim must have a citation [N] referencing the evidence above.

Write in Chinese (中文) to match the report language."""

    @staticmethod
    def evaluate_source_prompt(url: str, content: str) -> str:
        """Prompt for evaluating source quality."""
        return f"""Evaluate the following source for use in an academic research report.

URL: {url}

CONTENT EXCERPT:
{content[:2000]}

Evaluate:
1. Reliability (academic paper, official docs, tech blog, news, forum)
2. Relevance to code generation research (0-1)
3. Timeliness (is the information recent?) (0-1)
4. Contains verifiable data/benchmarks? (yes/no)

Return a JSON object:
{{
  "reliability": "academic_paper|official_docs|tech_blog|news|forum|unknown",
  "relevance_score": 0.0-1.0,
  "timeliness_score": 0.0-1.0,
  "has_verifiable_data": true/false,
  "notes": "Brief assessment"
}}

Return ONLY the JSON object."""
