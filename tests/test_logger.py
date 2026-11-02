import json
import logging
import sys
import unittest

from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from logger import CustomJsonFormatter, setup_logger, setup_browser_trace


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

    def test_browser_trace_file_filters_rotates_and_keeps_private_permissions(self):
        with TemporaryDirectory() as directory:
            logger = setup_logger('trace-file-test')
            path = Path(directory) / 'traces.jsonl'
            setup_browser_trace(logger, path)
            handler = logger.handlers[-1]
            handler.maxBytes = 256
            try:
                logger.info('sensitive non-trace message')
                for i in range(10):
                    logger.info('Netflix browser trace', extra={'run_id': 'fixture', 'event': 'finished', 'sequence': i})
                files = list(Path(directory).glob('traces.jsonl*'))
                self.assertEqual(len(files), 4)
                for file in files:
                    self.assertEqual(file.stat().st_mode & 0o777, 0o600)
                    content = file.read_text()
                    self.assertNotIn('sensitive', content)
                    for line in content.splitlines():
                        self.assertEqual(json.loads(line)['run_id'], 'fixture')
            finally:
                handler.close()
                logger.removeHandler(handler)

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
