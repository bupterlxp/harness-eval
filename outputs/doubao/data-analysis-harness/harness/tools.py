from typing import Dict, List, Callable, Any, Optional, Tuple
from pandas import DataFrame
from .schemas import ValidationResult


class ToolRegistry:
    """Registry for analysis tools with input/output validation"""

    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {
            "data_loader": {},
            "quality_checker": {},
            "preprocessor": {},
            "explorer": {},
            "trend_analyzer": {},
            "region_analyzer": {},
            "category_analyzer": {},
            "channel_analyzer": {},
            "validator": {},
            "reporter": {}
        }

    def register_tool(
        self,
        category: str,
        name: str,
        func: Callable,
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        description: str = ""
    ) -> None:
        """Register a tool in the registry"""
        if category not in self.tools:
            raise ValueError(f"Unknown tool category: {category}")

        self.tools[category][name] = {
            "function": func,
            "input_schema": input_schema or {},
            "output_schema": output_schema or {},
            "description": description
        }

    def get_tool(self, category: str, name: str) -> Optional[Dict[str, Any]]:
        """Get a tool from the registry"""
        return self.tools.get(category, {}).get(name)

    def list_tools(self, category: Optional[str] = None) -> List[Tuple[str, str, Dict[str, Any]]]:
        """List all registered tools"""
        tools_list = []
        if category:
            for name, tool in self.tools.get(category, {}).items():
                tools_list.append((category, name, tool))
        else:
            for cat, cat_tools in self.tools.items():
                for name, tool in cat_tools.items():
                    tools_list.append((cat, name, tool))
        return tools_list

    def execute_tool(
        self,
        category: str,
        name: str,
        *args,
        **kwargs
    ) -> Tuple[Any, ValidationResult]:
        """Execute a tool with validation"""
        tool = self.get_tool(category, name)
        if not tool:
            raise ValueError(f"Tool {name} not found in category {category}")

        # Validate input if schema exists
        validation_result = ValidationResult(is_valid=True)
        if tool["input_schema"]:
            validation_result = self._validate_input(args, kwargs, tool["input_schema"])

        if not validation_result.is_valid:
            return None, validation_result

        # Execute the tool
        try:
            result = tool["function"](*args, **kwargs)

            # Validate output if schema exists
            if tool["output_schema"]:
                output_validation = self._validate_output(result, tool["output_schema"])
                validation_result.errors.extend(output_validation.errors)
                validation_result.warnings.extend(output_validation.warnings)
                validation_result.checks_performed += output_validation.checks_performed
                validation_result.is_valid = validation_result.is_valid and output_validation.is_valid

            return result, validation_result

        except Exception as e:
            validation_result.errors.append(f"Tool execution failed: {str(e)}")
            validation_result.is_valid = False
            return None, validation_result

    def _validate_input(self, args: tuple, kwargs: dict, schema: Dict[str, Any]) -> ValidationResult:
        """Validate tool input against schema"""
        result = ValidationResult(checks_performed=1)

        # Simple validation for demonstration
        # In real implementation, would validate against schema
        if "required_columns" in schema:
            if len(args) > 0 and isinstance(args[0], DataFrame):
                df = args[0]
                missing_cols = [col for col in schema["required_columns"] if col not in df.columns]
                if missing_cols:
                    result.errors.append(f"Missing required columns: {missing_cols}")
                    result.is_valid = False

        if "required_fields" in schema:
            missing_fields = [f for f in schema["required_fields"] if f not in kwargs]
            if missing_fields:
                result.errors.append(f"Missing required keyword fields: {missing_fields}")
                result.is_valid = False

        return result

    def _validate_output(self, output: Any, schema: Dict[str, Any]) -> ValidationResult:
        """Validate tool output against schema"""
        result = ValidationResult(checks_performed=1)

        if isinstance(output, DataFrame):
            if "required_columns" in schema:
                missing_cols = [col for col in schema["required_columns"] if col not in output.columns]
                if missing_cols:
                    result.errors.append(f"Output missing required columns: {missing_cols}")
                    result.is_valid = False

            if "shape" in schema:
                expected_shape = tuple(schema["shape"])
                actual_shape = output.shape
                if actual_shape != expected_shape:
                    result.errors.append(f"Output shape mismatch: expected {expected_shape}, got {actual_shape}")
                    result.is_valid = False

        return result