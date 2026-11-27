"""Central logging: configuration in settings.LOGGING and the shared run markers."""

import logging

from django.conf import settings
from django.test import SimpleTestCase

from repowering.logging_utils import log_run


class LoggingConfigurationTests(SimpleTestCase):
    """Code only calls logging.getLogger(__name__); settings decide where it goes."""

    def handlers_of(self, logger_name):
        return settings.LOGGING["loggers"][logger_name]["handlers"]

    def test_each_area_has_its_own_file(self):
        self.assertEqual(settings.LOG_FILES["downloads"].name, "download_mastr_wind.log")
        self.assertEqual(settings.LOG_FILES["importing"].name, "import_wind_data.log")
        self.assertEqual(settings.LOG_FILES["rag"].name, "ragapp.log")
        self.assertEqual(settings.LOG_FILES["app"].name, "windenergy.log")

    def test_module_paths_are_routed_to_their_area(self):
        self.assertEqual(self.handlers_of("windenergy.management.commands.download_mastr_wind"),
                         ["downloads_file"])
        self.assertEqual(self.handlers_of("open-MaStR"), ["downloads_file"])
        self.assertEqual(self.handlers_of("windenergy.management.commands.import_wind_data"),
                         ["importing_file"])
        self.assertEqual(self.handlers_of("windenergy"), ["console", "app_file"])
        self.assertEqual(self.handlers_of("ragapp"), ["rag_file"])

    def test_commands_log_under_their_module_name(self):
        from ragapp.management.commands import import_context_documents, import_rag_documents
        from windenergy.management.commands import download_mastr_wind, import_wind_data
        for module in (download_mastr_wind, import_wind_data,
                       import_context_documents, import_rag_documents):
            with self.subTest(module.__name__):
                self.assertEqual(module.logger.name, module.__name__)

    def test_nothing_is_written_to_files_during_tests(self):
        self.assertTrue(settings.RUNNING_TESTS)
        for name, handler in settings.LOGGING["handlers"].items():
            with self.subTest(name):
                self.assertEqual(handler["class"], "logging.NullHandler")


class LogRunTests(SimpleTestCase):
    def test_successful_run_is_marked(self):
        logger = logging.getLogger("windenergy.tests.log_run")
        with self.assertLogs(logger, "INFO") as logs:
            with log_run(logger, "demo", source="x.db"):
                logger.info("working")
        self.assertEqual([line.split(":", 2)[2] for line in logs.output],
                         ["STARTED: demo (source=x.db)", "working", "SUCCEEDED: demo"])

    def test_failed_run_is_marked_and_error_is_raised(self):
        logger = logging.getLogger("windenergy.tests.log_run")
        with self.assertLogs(logger, "INFO") as logs:
            with self.assertRaises(ValueError):
                with log_run(logger, "demo"):
                    raise ValueError("broken")
        output = "\n".join(logs.output)
        self.assertIn("FAILED: demo", output)
        self.assertNotIn("SUCCEEDED", output)
