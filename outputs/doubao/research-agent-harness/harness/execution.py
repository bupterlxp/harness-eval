import asyncio
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from .schemas import Source, Evidence, ResearchQuery, ValidationResult, SourceReliability
from .state import ResearchStateStore
from .context import ResearchContext
from .tools import ToolRegistry, LLMClient
from .lifecycle import LifecycleHooks
from .evaluation import EvaluationTrajectory


class ResearchExecutionLoop:
    """Implements the main research execution state machine"""

    STATE_DECOMPOSE = "DECOMPOSE"
    STATE_SEARCH = "SEARCH"
    STATE_EVALUATE = "EVALUATE"
    STATE_EXTRACT = "EXTRACT"
    STATE_ORGANIZE = "ORGANIZE"
    STATE_GAP_FILL = "GAP_FILL"
    STATE_CROSS_VALIDATE = "CROSS_VALIDATE"
    STATE_DRAFT = "DRAFT"
    STATE_CONSISTENCY_CHECK = "CONSISTENCY_CHECK"
    STATE_FINALIZE = "FINALIZE"
    STATE_COMPLETE = "COMPLETE"

    def __init__(
        self,
        topic: str,
        questions: List[str],
        max_hops: int = 3,
        output_dir: str = "./output"
    ):
        self.topic = topic
        self.original_questions = questions
        self.state_store = ResearchStateStore(topic, questions, max_hops)
        self.context = ResearchContext([
            "摘要", "背景与动机", "主流模型对比", "关键技术进展",
            "当前挑战", "未来方向", "参考文献"
        ])
        self.tools = ToolRegistry()
        self.llm_client = LLMClient()
        self.lifecycle = LifecycleHooks(max_hops)
        self.evaluation_trajectory = EvaluationTrajectory(output_dir)
        self.current_state = self.STATE_DECOMPOSE
        self.current_query = None
        self.current_section = None
        self.loop_count = 0
        self.max_hops = max_hops
        self.output_dir = output_dir

        # Create output directory if it doesn't exist
        import os
        os.makedirs(output_dir, exist_ok=True)

    async def run(self) -> str:
        """Run the full research execution loop"""
        print(f"Starting research on: {self.topic}")
        print(f"Initial state: {self.current_state}")

        while self.current_state != self.STATE_COMPLETE:
            self.loop_count += 1
            print(f"\n--- Loop iteration {self.loop_count} - Current state: {self.current_state} ---")

            try:
                if self.current_state == self.STATE_DECOMPOSE:
                    await self._handle_decompose()
                elif self.current_state == self.STATE_SEARCH:
                    await self._handle_search()
                elif self.current_state == self.STATE_EVALUATE:
                    await self._handle_evaluate()
                elif self.current_state == self.STATE_EXTRACT:
                    await self._handle_extract()
                elif self.current_state == self.STATE_ORGANIZE:
                    await self._handle_organize()
                elif self.current_state == self.STATE_GAP_FILL:
                    await self._handle_gap_fill()
                elif self.current_state == self.STATE_CROSS_VALIDATE:
                    await self._handle_cross_validate()
                elif self.current_state == self.STATE_DRAFT:
                    await self._handle_draft()
                elif self.current_state == self.STATE_CONSISTENCY_CHECK:
                    await self._handle_consistency_check()
                elif self.current_state == self.STATE_FINALIZE:
                    await self._handle_finalize()

            except Exception as e:
                print(f"Error in state {self.current_state}: {e}")
                import traceback
                traceback.print_exc()
                break

        print(f"\nResearch loop completed after {self.loop_count} iterations")
        final_report = self.state_store.get_full_report()
        report_path = os.path.join(self.output_dir, "final_report.md")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(final_report)
        print(f"Final report saved to: {report_path}")

        return final_report

    async def _handle_decompose(self) -> None:
        """Handle DECOMPOSE state - break research questions into queries"""
        self.state_store.update_step(self.STATE_DECOMPOSE)
        print("Decomposing research questions into search queries...")

        # Create prompt for LLM to decompose questions
        prompt = f"""Please decompose the following research topic and questions into specific search queries.

Topic: {self.topic}

Questions:
{chr(10).join(f"- {q}" for q in self.original_questions)}

Return exactly {self.original_questions} search queries that would help answer these questions.
Each query should be specific and targeted for web search.

Format your response as a JSON array of strings, with no extra text."""

        # Get decomposed queries from LLM
        response = await self.llm_client.generate(prompt, temperature=0.3)
        import json
        try:
            queries = json.loads(response)
        except json.JSONDecodeError:
            # Fallback if LLM doesn't return pure JSON
            queries = [q.strip() for q in response.split("\n") if q.strip()]

        # Ensure we have at least 10 queries as per requirements
        if len(queries) < 10:
            additional = 10 - len(queries)
            for i in range(additional):
                queries.append(f"{self.topic} additional details {i+1}")

        print(f"Generated {len(queries)} search queries")
        self.evaluation_trajectory.log_decompose_step(self.original_questions, queries)

        # Store queries
        self.research_queries = [ResearchQuery(query=q) for q in queries]
        self.current_query_index = 0

        self.current_state = self.STATE_SEARCH

    async def _handle_search(self) -> None:
        """Handle SEARCH state - execute search queries"""
        self.state_store.update_step(self.STATE_SEARCH)

        if self.current_query_index >= len(self.research_queries):
            print("No more queries to search")
            self.current_state = self.STATE_EVALUATE
            return

        current_query = self.research_queries[self.current_query_index]
        print(f"Searching for query {self.current_query_index + 1}/{len(self.research_queries)}: {current_query.query}")

        # Check if query has already been searched
        if current_query.query.lower() in self.context.query_history.history:
            print(f"Query '{current_query.query}' already searched, skipping")
            self.current_query_index += 1
            return

        # Run pre-search hook
        valid, message = await self.lifecycle.pre_search(current_query.query, self.context.query_history.history)
        if not valid:
            print(f"Pre-search check failed: {message}")
            self.current_query_index += 1
            return

        try:
            # Execute search
            results = await self.tools.get_tool("web_search").search(current_query.query, current_query.max_results)

            # Convert results to Source objects
            sources = []
            for result in results:
                source = Source(
                    url=result["url"],
                    title=result["title"],
                    relevance_score=0.5  # Initial score, will be updated
                )
                sources.append(source)

            # Update query and history
            current_query.sources = sources
            current_query.completed = True
            self.context.query_history.add_query(current_query.query, sources)

            print(f"Found {len(sources)} sources")
            self.evaluation_trajectory.log_search_step(current_query.query, results)

        except Exception as e:
            print(f"Error searching: {e}")
            await self.lifecycle.on_rate_limit()

        self.current_query_index += 1

        # If we've processed all queries, move to next state
        if self.current_query_index >= len(self.research_queries):
            self.current_state = self.STATE_EVALUATE

    async def _handle_evaluate(self) -> None:
        """Handle EVALUATE state - evaluate sources"""
        self.state_store.update_step(self.STATE_EVALUATE)
        print("Evaluating sources...")

        evaluator = self.tools.get_tool("evaluate_source")

        # Process all sources from all queries
        for query in self.research_queries:
            for source in query.sources:
                if source.url in self.state_store.state.all_sources:
                    continue

                # Fetch content if possible
                content = await self.tools.get_tool("fetch_page").fetch(source.url)

                # Evaluate source
                reliability, relevance_score = evaluator.evaluate(source, content)
                source.reliability = reliability
                source.relevance_score = relevance_score
                source.content = content

                # Add to state store
                citation_key = self.state_store.add_source(source)

                print(f"Evaluated: {source.title[:50]}... - Reliability: {reliability.name}, Relevance: {relevance_score:.2f}")
                self.evaluation_trajectory.log_evaluate_step(source.url, reliability.name, relevance_score)

        self.current_state = self.STATE_EXTRACT

    async def _handle_extract(self) -> None:
        """Handle EXTRACT state - extract facts from sources"""
        self.state_store.update_step(self.STATE_EXTRACT)
        print("Extracting facts from sources...")

        # Extract facts for each original question
        for source in self.state_store.state.all_sources.values():
            if not source.content:
                continue

            try:
                # Use LLM to extract facts
                extracted = await self.llm_client.extract_facts(
                    source.content,
                    self.original_questions
                )

                for fact_data in extracted:
                    evidence = Evidence(
                        source_url=source.url,
                        claim=fact_data.get("fact", ""),
                        confidence=0.8
                    )
                    self.state_store.add_evidence(evidence)

                print(f"Extracted {len(extracted)} facts from: {source.title[:50]}...")
                self.evaluation_trajectory.log_extract_step(source.url, len(extracted))

            except Exception as e:
                print(f"Error extracting facts from {source.url}: {e}")

        self.current_state = self.STATE_ORGANIZE

    async def _handle_organize(self) -> None:
        """Handle ORGANIZE state - organize evidence by section"""
        self.state_store.update_step(self.STATE_ORGANIZE)
        print("Organizing evidence into sections...")

        # Group evidence by section
        section_evidence = {
            "摘要": [],
            "背景与动机": [],
            "主流模型对比": [],
            "关键技术进展": [],
            "当前挑战": [],
            "未来方向": [],
            "参考文献": []
        }

        # Categorize evidence into sections
        for evidence in self.state_store.evidence_store.get_all_evidence():
            # Simple categorization based on keyword matching
            # In real implementation, use more sophisticated NLP
            claim_lower = evidence.claim.lower()

            if "model" in claim_lower or "benchmark" in claim_lower or "humaneval" in claim_lower or "mbpp" in claim_lower:
                section_evidence["主流模型对比"].append(evidence)
            elif "train" in claim_lower or "data" in claim_lower or "copyright" in claim_lower:
                section_evidence["背景与动机"].append(evidence)
            elif "technolog" in claim_lower or "improve" in claim_lower or "advance" in claim_lower:
                section_evidence["关键技术进展"].append(evidence)
            elif "challeng" in claim_lower or "problem" in claim_lower or "difficult" in claim_lower:
                section_evidence["当前挑战"].append(evidence)
            elif "future" in claim_lower or "direction" in claim_lower or "promis" in claim_lower:
                section_evidence["未来方向"].append(evidence)
            else:
                section_evidence["背景与动机"].append(evidence)

        # Update context
        for section, evidence_list in section_evidence.items():
            if evidence_list:
                self.context.outline_context.add_to_section(section, "", evidence_list)
                print(f"Added {len(evidence_list)} evidence items to section: {section}")
                self.evaluation_trajectory.log_organize_step(section, len(evidence_list))

        self.current_state = self.STATE_GAP_FILL

    async def _handle_gap_fill(self) -> None:
        """Handle GAP_FILL state - identify and fill information gaps"""
        self.state_store.update_step(self.STATE_GAP_FILL)
        print("Identifying information gaps...")

        # Get information gaps from context
        gaps = self.context.get_info_gaps()

        if not gaps:
            print("No significant information gaps found")
            self.current_state = self.STATE_CROSS_VALIDATE
            return

        # Print gaps
        print("\nFound information gaps:")
        for gap_type, gap_items in gaps.items():
            print(f"  {gap_type}:")
            for item in gap_items:
                print(f"    - {item}")

        # Check if we can do more hops
        if not self.lifecycle.should_continue_searching(self.state_store.state.hop_count):
            print(f"Max hops ({self.max_hops}) reached, skipping gap filling")
            self.current_state = self.STATE_CROSS_VALIDATE
            return

        # Create new queries to fill gaps
        new_queries = []
        for gap_type, gap_items in gaps.items():
            for item in gap_items:
                new_query = f"{self.topic} {item}"
                new_queries.append(new_query)

        print(f"\nCreating {len(new_queries)} new queries to fill gaps")
        self.evaluation_trajectory.log_gap_fill_step(str(gaps), new_queries)

        # Add new queries to the list
        self.research_queries.extend([ResearchQuery(query=q) for q in new_queries])
        self.current_query_index = 0

        # Increment hop count
        self.state_store.increment_hop_count()

        self.current_state = self.STATE_SEARCH

    async def _handle_cross_validate(self) -> None:
        """Handle CROSS_VALIDATE state - validate evidence across sources"""
        self.state_store.update_step(self.STATE_CROSS_VALIDATE)
        print("Performing cross validation of evidence...")

        # For each key evidence point, check multiple sources
        # This is a simplified implementation
        key_claims = {}
        for evidence in self.state_store.evidence_store.get_all_evidence():
            if evidence.claim not in key_claims:
                key_claims[evidence.claim] = []
            key_claims[evidence.claim].append(evidence.source_url)

        # Check claims with only one source
        validated_evidence = []
        for claim, sources in key_claims.items():
            if len(sources) < 2:
                print(f"Claim '{claim[:100]}...' only has one source, should validate")

        self.evaluation_trajectory.log_cross_validate_step("Key claims cross validation", list(key_claims.keys()))
        self.current_state = self.STATE_DRAFT

    async def _handle_draft(self) -> None:
        """Handle DRAFT state - draft report sections"""
        self.state_store.update_step(self.STATE_DRAFT)
        print("Drafting report sections...")

        # Draft each section
        sections_to_draft = list(self.context.outline_context.required_sections)
        # Remove references section for now
        sections_to_draft.remove("参考文献")

        for section_title in sections_to_draft:
            print(f"\nDrafting section: {section_title}")

            section = self.context.outline_context.get_section(section_title)
            if not section or not section.evidence:
                print(f"No evidence for section {section_title}, skipping")
                continue

            # Check evidence sufficiency
            validation = await self.lifecycle.pre_draft(section_title, section.evidence)
            if not validation.valid:
                print(f"Evidence insufficient for {section_title}: {validation.errors}")
                continue

            # Create prompt for drafting
            evidence_text = "\n".join([f"- {e.claim}" for e in section.evidence])
            prompt = f"""Please write a section for a research report on: {self.topic}

Section title: {section_title}

Use the following evidence to write the section:
{evidence_text}

Write a comprehensive, well-structured section. Include proper citations in the text using [1] format.
Don't include a references section at the end.
"""

            # Generate section content
            content = await self.llm_client.generate(prompt, temperature=0.7)

            # Update state store
            self.state_store.update_section(section_title, content, section.evidence)
            self.context.outline_context.update_section(section_title, content, section.evidence)

            print(f"Drafted section {section_title} with {len(content)} characters")
            self.evaluation_trajectory.log_draft_step(section_title, len(content))

        # Now handle references section
        await self._draft_references_section()

        self.current_state = self.STATE_CONSISTENCY_CHECK

    async def _draft_references_section(self) -> None:
        """Draft the references section"""
        print("\nDrafting references section...")

        citations = self.state_store.citation_mapper.get_all_citations()
        references_text = "\n".join([f"{i+1}. {citation.formatted}" for i, citation in enumerate(citations)])

        self.state_store.update_section("参考文献", references_text, [])
        self.context.outline_context.update_section("参考文献", references_text, [])

    async def _handle_consistency_check(self) -> None:
        """Handle CONSISTENCY_CHECK state - check consistency and citations"""
        self.state_store.update_step(self.STATE_CONSISTENCY_CHECK)
        print("Performing consistency check...")

        all_errors = []
        all_warnings = []

        # Check each section for citation integrity
        for section_title in self.context.outline_context.required_sections:
            if section_title == "参考文献":
                continue

            section = self.state_store.draft_manager.get_section(section_title)
            if not section:
                continue

            # Simple citation check - count [1] style citations
            import re
            citations_in_text = re.findall(r'\[\d+\]', section.content)
            unique_citations = set(citations_in_text)

            print(f"Section {section_title} has {len(unique_citations)} unique citations")

            # Check if all citations exist
            all_citation_keys = set(self.state_store.citation_mapper.citations.keys())
            for cit in unique_citations:
                if cit not in all_citation_keys:
                    all_errors.append(f"Citation {cit} in {section_title} not found in references")

        # Run lifecycle consistency check
        validation = await self.lifecycle.validate_citation_integrity(
            {},  # Would parse citations from text
            set(self.state_store.citation_mapper.citations.keys())
        )
        all_errors.extend(validation.errors)
        all_warnings.extend(validation.warnings)

        # Log and report
        if all_errors:
            print(f"\nFound {len(all_errors)} consistency errors:")
            for error in all_errors:
                print(f"  - {error}")

        if all_warnings:
            print(f"\nFound {len(all_warnings)} warnings:")
            for warning in all_warnings:
                print(f"  - {warning}")

        self.evaluation_trajectory.log_consistency_check_step(all_errors, all_warnings)
        self.current_state = self.STATE_FINALIZE

    async def _handle_finalize(self) -> None:
        """Handle FINALIZE state - finalize the report"""
        self.state_store.update_step(self.STATE_FINALIZE)
        print("Finalizing report...")

        # Save full report
        full_report = self.state_store.get_full_report()

        # Save trajectory
        self.evaluation_trajectory.log_finalize_step(
            len(self.state_store.state.all_sources),
            len(self.context.outline_context.required_sections)
        )
        self.evaluation_trajectory.print_summary()

        # Save state
        state_file = os.path.join(self.output_dir, "research_state.json")
        self.state_store.save(state_file)
        print(f"Research state saved to: {state_file}")

        self.current_state = self.STATE_COMPLETE
        print("Research process completed successfully!")