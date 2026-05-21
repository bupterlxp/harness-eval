"""
Execution Loop - Drives the research process with explicit state machine
"""

import os
import time
from typing import Dict, List, Any, Optional
from pathlib import Path
import json

from .tools import ToolRegistry, Source
from .context import ContextManager
from .state import StateStore
from .lifecycle import LifecycleHooks
from .evaluation import Evaluator


class TaskSpec:
    """Task specification for research tasks"""
    def __init__(
        self,
        research_questions: List[str],
        min_sources: int = 10,
        max_words: int = 4000,
        required_sections: Optional[List[str]] = None,
        max_hops: int = 3,
        output_dir: str = "./output",
        constraints: Optional[List[str]] = None,
    ):
        self.research_questions = research_questions
        self.min_sources = min_sources
        self.max_words = max_words
        self.required_sections = required_sections or []
        self.max_hops = max_hops
        self.output_dir = output_dir
        self.constraints = constraints or []


class ExecutionLoop:
    """
    Main execution loop that drives the research process
    Implements an explicit state machine with max_hops termination condition
    """

    def __init__(
        self,
        task_spec: TaskSpec,
        tool_registry: ToolRegistry,
        context_manager: ContextManager,
        state_store: StateStore,
        lifecycle_hooks: LifecycleHooks,
        evaluator: Evaluator
    ):
        self.task_spec = task_spec
        self.tool_registry = tool_registry
        self.context_manager = context_manager
        self.state_store = state_store
        self.lifecycle_hooks = lifecycle_hooks
        self.evaluator = evaluator

        # Initialize state
        self.current_hop = 0
        self._initialize_state()

        # Track progress
        self.collected_sources: List[Dict[str, Any]] = []
        self.extracted_facts: List[Dict[str, Any]] = []

    def _initialize_state(self) -> None:
        """Initialize the research state"""
        task_spec_dict = {
            "research_questions": self.task_spec.research_questions,
            "min_sources": self.task_spec.min_sources,
            "max_words": self.task_spec.max_words,
            "required_sections": self.task_spec.required_sections,
            "max_hops": self.task_spec.max_hops,
            "output_dir": self.task_spec.output_dir,
            "constraints": self.task_spec.constraints
        }
        self.state_store.initialize(task_spec_dict)
        self.evaluator.start_session()

    def run(self) -> Dict[str, Any]:
        """
        Main execution loop
        """
        print(f"Starting research with max_hops={self.task_spec.max_hops}")

        while self.current_hop < self.task_spec.max_hops:
            print(f"\n=== Research Hop {self.current_hop + 1}/{self.task_spec.max_hops} ===")

            # Execute one research hop
            result = self._execute_hop()

            # Update trajectory
            self.evaluator.log_step(
                query=f"Hop {self.current_hop + 1}",
                results_count=len(result.get("sources", [])),
                evaluation_result={"status": "completed"},
                facts_extracted=len(result.get("facts", []))
            )

            # Update state
            self.current_hop += 1
            self.state_store.update_progress(
                current_hop=self.current_hop,
                sources_collected=len(self.collected_sources),
                facts_extracted=len(self.extracted_facts)
            )

            # Check if we have enough information
            if self._is_sufficient_evidence():
                print("\n✅ Sufficient evidence collected, stopping research early")
                break

        # Finalize research
        self.evaluator.end_session()
        self.state_store.save_trajectory()

        # Generate final report
        report_result = self._generate_final_report()

        return report_result

    def _execute_hop(self) -> Dict[str, Any]:
        """
        Execute a single research hop
        """
        # Step 1: Generate search queries
        queries = self._generate_search_queries()

        # Step 2: Perform searches
        all_sources = []
        for query in queries:
            # Check for duplicate queries
            if not self.lifecycle_hooks.pre_search_deduplicate(query):
                continue

            # Execute search
            search_tool = self.tool_registry.get_tool("search_web")
            if search_tool:
                results = search_tool(query, num_results=5)
                # Filter out already visited URLs
                filtered_results = self.lifecycle_hooks.pre_search_url_filter(results)
                all_sources.extend(filtered_results)

        # Step 3: Evaluate and process sources
        processed_sources = []
        for source_data in all_sources:
            # Evaluate source credibility
            evaluate_tool = self.tool_registry.get_tool("evaluate_source")
            if evaluate_tool:
                eval_result = evaluate_tool(source_data)
                source_data["credibility"] = eval_result["credibility"]
                source_data["source_type"] = eval_result["source_type"]

            # Extract content
            extract_tool = self.tool_registry.get_tool("extract_content")
            if extract_tool:
                try:
                    content = extract_tool(source_data["url"])
                    source_data["content"] = content
                except Exception:
                    source_data["content"] = ""

            processed_sources.append(source_data)
            self.collected_sources.append(source_data)
            self.state_store.add_source(source_data)

        # Mark URLs as visited
        self.lifecycle_hooks.mark_urls_visited(processed_sources)

        # Step 4: Extract facts from sources
        extracted_facts = self._extract_facts_from_sources(processed_sources)

        return {
            "sources": processed_sources,
            "facts": extracted_facts,
            "queries_used": queries
        }

    def _generate_search_queries(self) -> List[str]:
        """
        Generate search queries based on research questions
        """
        # Simple query generation - in real implementation, use LLM to decompose questions
        base_queries = []
        for question in self.task_spec.research_questions:
            # Split question into multiple queries
            base_queries.append(question)
            base_queries.append(f"{question} latest")
            base_queries.append(f"{question} overview")

        return base_queries

    def _extract_facts_from_sources(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract factual statements from sources
        """
        extracted_facts = []

        for source in sources:
            source_id = source["id"]
            content = source.get("content", "")

            if not content:
                continue

            # Simple fact extraction - in real implementation, use LLM
            # Split content into sentences and treat each as a fact
            sentences = [s.strip() for s in content.split(".") if s.strip()]

            for sentence in sentences[:5]:  # Limit to first 5 sentences per source
                fact_data = {
                    "content": sentence,
                    "source_ids": [source_id],
                    "confidence": 1.0
                }
                extracted_facts.append(fact_data)
                self.extracted_facts.append(fact_data)
                self.state_store.add_fact(fact_data)

        return extracted_facts

    def _is_sufficient_evidence(self) -> bool:
        """
        Check if we have collected enough evidence to proceed to reporting
        """
        has_enough_sources = len(self.collected_sources) >= self.task_spec.min_sources
        has_enough_facts = len(self.extracted_facts) >= 20  # Arbitrary threshold

        return has_enough_sources and has_enough_facts

    def _generate_final_report(self) -> Dict[str, Any]:
        """
        Generate the final structured report
        """
        print("\n=== Generating Final Report ===")

        # Create output directory
        output_dir = self.task_spec.output_dir
        os.makedirs(output_dir, exist_ok=True)

        # Generate report content
        report_content = {
            "research_questions": self.task_spec.research_questions,
            "summary": "This is a mock research report generated by the harness.",
            "sections": {},
            "sources": [],
            "citation_integrity": {
                "total_citations": 0,
                "orphaned": 0,
                "unused": 0
            },
            "gaps": [],
            "trajectory": self.state_store.get_trajectory_path()
        }

        # Process sources for final output
        for source in self.collected_sources:
            source_dict = {
                "id": source["id"],
                "url": source["url"],
                "title": source["title"],
                "credibility": source["credibility"]
            }
            report_content["sources"].append(source_dict)

        # Validate citation integrity
        citation_check = self.lifecycle_hooks.validate_citation_integrity(
            report_content["sections"],
            self.collected_sources
        )
        report_content["citation_integrity"] = citation_check

        # Save report
        report_path = os.path.join(output_dir, "research_report.json")
        with open(report_path, "w") as f:
            json.dump(report_content, f, indent=2)

        # Determine status
        if len(self.collected_sources) >= self.task_spec.min_sources and citation_check["orphaned"] == 0:
            status = "success"
        elif len(self.collected_sources) >= 5:
            status = "partial"
        else:
            status = "failed"

        return {
            "status": status,
            "report_path": report_path,
            "sources": report_content["sources"],
            "citation_integrity": citation_check,
            "gaps": [],
            "trajectory": self.state_store.get_trajectory_path()
        }