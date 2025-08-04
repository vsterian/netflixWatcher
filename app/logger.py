"""Module providing custom JSON logging functionality"""
import json
import logging
import sys
import traceback
from datetime import datetime

LOG_RECORD_ATTRS = [
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
]


class CustomJsonFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        output = {}
        
        # Add core fields
        for key in ["name", "module", "funcName"]:
            output[key] = record.__dict__[key]

        output["message"] = record.__dict__["msg"]
        output["timestamp"] = (
            str(datetime.fromtimestamp(record.__dict__["created"]).isoformat()) + "Z"
        )

        # Add all 'extra' properties
        for key in [k for k in record.__dict__ if k not in LOG_RECORD_ATTRS]:
            output[key] = record.__dict__[key]

        # Add exception info if present
        if record.exc_info:
            output["exception"] = str(record.__dict__["exc_info"])
            output["stacktrace"] = ''.join(traceback.format_exception(*record.exc_info))

        return json.dumps(output)


def setup_logger(logger_name="netflixwatcher"):
    """Set up logger with console handler and custom JSON formatter"""
    logger = logging.getLogger(logger_name)
    
    # Clear any existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Set up console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(CustomJsonFormatter())
    logger.addHandler(console_handler)

    # Set log level
    logger.setLevel(logging.INFO)

    return logger