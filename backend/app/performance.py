import asyncio
import time
import functools
from typing import Any, Callable, Optional
from app.logging_config import get_logger, get_request_id

perf_logger = get_logger("performance")

SLOW_THRESHOLD_MS = 100


class PerformanceTracker:
    def __init__(self, operation: str, **context):
        self.operation = operation
        self.context = context
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.perf_counter()
        start = self.start_time or self.end_time
        duration_ms = (self.end_time - start) * 1000

        log_data = {
            "operation": self.operation,
            "duration_ms": round(duration_ms, 2),
            "success": exc_type is None,
        }
        log_data.update(self.context)

        if duration_ms > SLOW_THRESHOLD_MS:
            perf_logger.warning(f"Slow operation: {self.operation}", **log_data)
        else:
            perf_logger.debug(f"Operation: {self.operation}", **log_data)

        return False


def track_performance(operation_name: Optional[str] = None, **context_kwargs):
    def decorator(func: Callable) -> Callable:
        operation = operation_name or func.__name__

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                    duration_ms = (time.perf_counter() - start) * 1000
                    log_data = {
                        "operation": operation,
                        "duration_ms": round(duration_ms, 2),
                        "success": True,
                    }
                    log_data.update(context_kwargs)
                    if duration_ms > SLOW_THRESHOLD_MS:
                        perf_logger.warning(f"Slow operation: {operation}", **log_data)
                    else:
                        perf_logger.debug(f"Operation: {operation}", **log_data)
                    return result
                except Exception as e:
                    duration_ms = (time.perf_counter() - start) * 1000
                    log_data = {
                        "operation": operation,
                        "duration_ms": round(duration_ms, 2),
                        "success": False,
                        "error": str(e),
                    }
                    log_data.update(context_kwargs)
                    perf_logger.error(f"Operation failed: {operation}", **log_data)
                    raise

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000
                log_data = {
                    "operation": operation,
                    "duration_ms": round(duration_ms, 2),
                    "success": True,
                }
                log_data.update(context_kwargs)
                if duration_ms > SLOW_THRESHOLD_MS:
                    perf_logger.warning(f"Slow operation: {operation}", **log_data)
                else:
                    perf_logger.debug(f"Operation: {operation}", **log_data)
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start) * 1000
                log_data = {
                    "operation": operation,
                    "duration_ms": round(duration_ms, 2),
                    "success": False,
                    "error": str(e),
                }
                log_data.update(context_kwargs)
                perf_logger.error(f"Operation failed: {operation}", **log_data)
                raise

        return sync_wrapper

    return decorator
