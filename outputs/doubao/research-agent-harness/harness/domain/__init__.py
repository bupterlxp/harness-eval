"""
Domain-specific tools and prompts for the research harness
"""
from typing import List, Dict, Optional, Any, Tuple
import json
from ..schemas import Source, Evidence


# 领域专用提示词模板
DOMAIN_PROMPTS = {
    "question_decomposition": """请将以下研究问题分解为具体的检索查询。

主题: {topic}

研究问题:
{questions}

请返回 exactly {num_queries} 个搜索查询，这些查询应有助于回答这些问题。
每个查询都应该针对网络搜索进行具体且有针对性的设计。

请以JSON数组字符串的形式返回您的答案，不添加任何额外文本。
""",

    "source_evaluation": """请评估以下来源的可靠性和相关性。

来源标题: {title}
来源URL: {url}

内容摘要:
{content}

请从0到10分给出相关性评分，并从以下类别中选择可靠性等级:
- ACADEMIC: 学术论文或同行评审文章
- TECHNICAL_BLOG: 技术博客或开发者文章
- OFFICIAL_DOC: 官方文档或权威资源
- NEWS: 新闻报道
- FORUM: 论坛或社区讨论
- UNKNOWN: 未知

请以JSON格式返回，包含'reliability'和'relevance_score'字段。
""",

    "fact_extraction": """请从以下内容中提取回答以下问题的事实信息。

问题:
{questions}

内容:
{content}

请以JSON数组的形式返回您的答案，每个对象包含'question', 'fact'和'source_url'字段。
只包含内容直接支持的事实。
""",

    "section_drafting": """请为研究报告撰写以下章节。

主题: {topic}
章节标题: {section_title}

使用以下证据来撰写章节:
{evidence_text}

请撰写一个全面、结构良好的章节。在文本中使用[1]格式包含适当的引用。
不要在末尾包含参考文献部分。
""",

    "summary_generation": """请为以下研究报告生成一个200字以内的摘要。

报告内容:
{report_content}

请确保摘要涵盖研究的主要发现、方法和结论。
""
}


class DomainPrompts:
    """管理领域专用提示词"""

    @staticmethod
    def get_prompt(name: str, **kwargs) -> str:
        """获取格式化的提示词"""
        if name not in DOMAIN_PROMPTS:
            raise ValueError(f"未知的提示词模板: {name}")
        return DOMAIN_PROMPTS[name].format(**kwargs)


class CodeGenerationDomain:
    """代码生成大模型领域专用工具"""

    # 常见代码生成模型列表
    POPULAR_MODELS = [
        "Codex", "GPT-4", "Claude", "StarCoder", "Llama",
        "CodeLlama", "PaLM-Coder", "CodeGeeX", "Incoder", "SantaCoder"
    ]

    # 常见基准测试
    STANDARD_BENCHMARKS = ["HumanEval", "MBPP", "BigCodeBench", "MultiPL-E", "APPS"]

    # 关键技术术语
    KEY_TERMS = {
        "instruction_tuning": "指令微调",
        "fill_in_the_middle": "中间填充",
        "repo_level_context": "仓库级上下文",
        "rlhf": "基于人类反馈的强化学习",
        "few_shot": "少样本学习",
        "zero_shot": "零样本学习",
        "retrieval_augmented": "检索增强生成"
    }

    @classmethod
    def extract_model_names(cls, text: str) -> List[str]:
        """从文本中提取模型名称"""
        models = []
        text_lower = text.lower()
        for model in cls.POPULAR_MODELS:
            if model.lower() in text_lower:
                models.append(model)
        return list(set(models))

    @classmethod
    def extract_benchmarks(cls, text: str) -> List[str]:
        """从文本中提取基准测试名称"""
        benchmarks = []
        text_lower = text.lower()
        for bench in cls.STANDARD_BENCHMARKS:
            if bench.lower() in text_lower:
                benchmarks.append(bench)
        return list(set(benchmarks))

    @staticmethod
    def format_model_comparison_table(models_data: List[Dict[str, Any]]) -> str:
        """格式化模型对比表格"""
        if not models_data:
            return "无模型数据"

        # 确定表格列
        columns = set()
        for model in models_data:
            columns.update(model.keys())
        columns = list(columns)

        # 构建Markdown表格
        table = "| 模型 | " + " | ".join(columns) + " |\n"
        table += "|------|" + "|" * len(columns) + "\n"

        for model in models_data:
            row = f"| {model.get('name', 'Unknown')} |"
            for col in columns:
                row += f" {model.get(col, 'N/A')} |"
            table += row + "\n"

        return table


class CitationFormatter:
    """引用格式化工具"""

    @staticmethod
    def format_arXiv(url: str, authors: List[str], year: int, title: str) -> str:
        """格式化arXiv引用"""
        return f"{', '.join(authors)}({year}). {title}. arXiv. {url}"

    @staticmethod
    def format_academic_paper(url: str, authors: List[str], year: int, title: str, journal: str) -> str:
        """格式化学术论文引用"""
        return f"{', '.join(authors)}({year}). {title}. {journal}. {url}"

    @staticmethod
    def format_blog_post(url: str, author: str, year: int, title: str, blog_name: str) -> str:
        """格式化博客文章引用"""
        return f"{author}({year}). {title}. {blog_name}. {url}"

    @staticmethod
    def format_official_doc(url: str, organization: str, year: int, title: str) -> str:
        """格式化官方文档引用"""
        return f"{organization}({year}). {title}. {url}"


class ResearchValidator:
    """研究验证工具"""

    @staticmethod
    def validate_report_structure(report: str, required_sections: List[str]) -> Tuple[bool, List[str]]:
        """验证报告结构是否包含所有必需章节"""
        sections_found = []
        for section in required_sections:
            if f"# {section}" in report:
                sections_found.append(section)

        missing = [s for s in required_sections if s not in sections_found]
        return len(missing) == 0, missing

    @staticmethod
    def count_citations(report: str) -> int:
        """统计报告中的引用数量"""
        import re
        return len(re.findall(r'\[\d+\]', report))

    @staticmethod
    def check_citation_integrity(report: str, references: List[str]) -> Tuple[bool, List[str]]:
        """检查引用完整性"""
        import re
        citations_in_text = re.findall(r'\[(\d+)\]', report)
        if not citations_in_text:
            return True, []

        max_citation = len(references)
        invalid = []
        for cit in citations_in_text:
            cit_num = int(cit)
            if cit_num < 1 or cit_num > max_citation:
                invalid.append(f"[{cit}] (引用编号超出范围)")

        return len(invalid) == 0, invalid

    @staticmethod
    def check_min_sources(count: int, min_count: int) -> bool:
        """检查是否有足够的来源"""
        return count >= min_count


# 预定义的研究问题模板
RESEARCH_QUESTION_TEMPLATES = {
    "code_generation": {
        "topic": "大语言模型在代码生成领域的最新进展与挑战",
        "questions": [
            "目前主流的代码生成大模型有哪些？它们在HumanEval和MBPP等基准上的表现如何？",
            "代码生成模型的训练数据来源有哪些？存在哪些数据质量和版权问题？",
            "从Codex到GPT-4到Claude，代码生成能力经历了哪些关键技术突破？",
            "当前代码生成模型在处理复杂、多文件项目时面临哪些挑战？",
            "代码生成模型在安全性方面存在哪些风险？如何评估生成代码的安全性？"
        ]
    }
}