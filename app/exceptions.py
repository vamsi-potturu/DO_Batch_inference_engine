class BatchNotFoundError(Exception):
    def __init__(self, batch_id: str):
        self.batch_id = batch_id
        super().__init__(f"Batch '{batch_id}' does not exist")


class BatchAlreadyProcessingError(Exception):
    def __init__(self, batch_id: str, status: str):
        self.batch_id = batch_id
        self.status = status
        super().__init__(f"Batch '{batch_id}' is already {status}")


class InvalidInputError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class InferenceMaxRetriesError(Exception):
    """Raised by the worker when a single prompt exhausts all retries.

    Caught inside the engine — never surfaces as an HTTP error.
    """
    def __init__(self, prompt_index: int, attempts: int):
        self.prompt_index = prompt_index
        self.attempts = attempts
        super().__init__(
            f"Prompt at index {prompt_index} failed after {attempts} attempts"
        )
