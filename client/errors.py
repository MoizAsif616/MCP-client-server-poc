def error_text(exc):
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(error_text(item) for item in exc.exceptions)
    return str(exc) or type(exc).__name__
