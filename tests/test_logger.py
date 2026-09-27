import json
import logging
import sys
import unittest

from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from logger import CustomJsonFormatter, setup_logger


class LoggerTest(unittest.TestCase):
    def test_formatter_serializes_standard_and_extra_fields(self):
        record = logging.LogRecord(
            "netflixwatcher", logging.INFO, "application.py", 42, "poll finished", (), None
        )
        record.request_id = "test-123"

        output = json.loads(CustomJsonFormatter().format(record))

        self.assertEqual(output["name"], "netflixwatcher")
        self.assertEqual(output["module"], "application")
        self.assertEqual(output["funcName"], record.funcName)
        self.assertEqual(output["message"], "poll finished")
        self.assertEqual(output["request_id"], "test-123")
        self.assertTrue(output["timestamp"].endswith("Z"))

    def test_formatter_includes_exception_details(self):
        try:
            raise RuntimeError("controlled failure")
        except RuntimeError:
            exception = sys.exc_info()
        record = logging.LogRecord(
            "netflixwatcher", logging.ERROR, "application.py", 7, "failed", (), exception
        )

        output = json.loads(CustomJsonFormatter().format(record))

        self.assertIn("RuntimeError", output["exception"])
        self.assertIn("controlled failure", output["stacktrace"])

    def test_setup_logger_replaces_handlers_and_sets_level(self):
        logger = logging.getLogger("logger-test")
        logger.handlers[:] = [logging.NullHandler(), logging.NullHandler()]
        with patch("logger.sys.stdout"):
            returned = setup_logger("logger-test")

        self.assertIs(returned, logger)
        self.assertEqual(logger.level, logging.INFO)
        self.assertEqual(len(logger.handlers), 1)
        self.assertIsInstance(logger.handlers[0], logging.StreamHandler)
        self.assertIsInstance(logger.handlers[0].formatter, CustomJsonFormatter)


if __name__ == "__main__":
    unittest.main()
