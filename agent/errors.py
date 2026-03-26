from .custom_types import StopReason


class AgentExecutionError(RuntimeError):
    def __init__(self, stop_reason: StopReason, message: str) -> None:
        super().__init__(message)
        self.stop_reason = stop_reason


class LLMExecutionError(AgentExecutionError):
    def __init__(self, message: str) -> None:
        super().__init__("llm_error", message)


class InvalidModelOutputError(AgentExecutionError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_model_output", message)


class ToolExecutionError(AgentExecutionError):
    def __init__(self, message: str) -> None:
        super().__init__("tool_error", message)
