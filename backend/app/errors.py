FORBIDDEN_MESSAGE_PARTS = ("http", "mongodb", "/", "\\", "traceback")

class AppError(Exception):
    DATA_UNAVAILABLE = "Not enough data is available to compute the analysis."
    INTERNAL_ANALYSIS = "An internal error occurred while computing the analysis."
    INVALID_REQUEST = "The request parameters are invalid."

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    @classmethod
    def unavailable(cls, message: str | None = None) -> "AppError":
        return cls("data_unavailable", message or cls.DATA_UNAVAILABLE, status=502)

    @classmethod
    def internal(cls, message: str | None = None) -> "AppError":
        return cls("internal_error", message or cls.INTERNAL_ANALYSIS, status=500)

    @classmethod
    def invalid_region(cls) -> "AppError":
        return cls("invalid_region", cls.INVALID_REQUEST, status=400)
