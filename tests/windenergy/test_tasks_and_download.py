"""Daily refresh task, MaStR download command and the chatbot adapter (no network)."""

import io
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from windenergy import services, tasks


class RefreshTaskTests(SimpleTestCase):
    def test_downloads_in_child_process_then_imports(self):
        with mock.patch.object(tasks.subprocess, "run") as run, \
                mock.patch.object(tasks, "call_command") as command:
            result = tasks.refresh_mastr_wind_data()
        args = run.call_args.args[0]
        self.assertEqual(args[-1], "download_mastr_wind")
        self.assertTrue(run.call_args.kwargs["check"])           # a failed download stops the task
        command.assert_called_once_with("import_wind_data")
        self.assertIn("downloaded and imported", result)

    def test_failed_download_does_not_import(self):
        import subprocess
        with mock.patch.object(tasks.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "x")), \
                mock.patch.object(tasks, "call_command") as command:
            with self.assertRaises(subprocess.CalledProcessError):
                tasks.refresh_mastr_wind_data()
        command.assert_not_called()

    def test_registered_task_name(self):
        self.assertEqual(tasks.refresh_mastr_wind_data.name, "windenergy.refresh_mastr_wind_data")


class DownloadCommandTests(TestCase):
    def run_download(self, *args):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fake_mastr = mock.MagicMock()

        @contextmanager
        def fake_capture(handler, home):
            yield fake_mastr

        target = "windenergy.management.commands.download_mastr_wind.capture_open_mastr_logs"
        with self.settings(BASE_DIR=Path(tmp.name)), mock.patch(target, fake_capture):
            call_command("download_mastr_wind", "--output-dir", tmp.name, *args, stdout=io.StringIO())
        return fake_mastr

    def test_downloads_wind_data_with_cleansing(self):
        mastr_class = self.run_download("--date", "20261127")
        download = mastr_class.return_value.download
        download.assert_called_once()
        self.assertEqual(download.call_args.kwargs["data"], "wind")
        self.assertEqual(download.call_args.kwargs["date"], "20261127")
        self.assertTrue(download.call_args.kwargs["bulk_cleansing"])

    def test_invalid_date_is_rejected_before_downloading(self):
        with self.assertRaises(CommandError):
            self.run_download("--date", "27.11.2026")

    def test_download_error_becomes_command_error(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        @contextmanager
        def failing_capture(handler, home):
            mastr = mock.MagicMock()
            mastr.return_value.download.side_effect = ConnectionError("offline")
            yield mastr

        target = "windenergy.management.commands.download_mastr_wind.capture_open_mastr_logs"
        with self.settings(BASE_DIR=Path(tmp.name)), mock.patch(target, failing_capture):
            with self.assertRaisesMessage(CommandError, "download failed"):
                call_command("download_mastr_wind", "--output-dir", tmp.name, stdout=io.StringIO())


class ChatbotAdapterTests(SimpleTestCase):
    def test_delegates_to_rag_service(self):
        with mock.patch("ragapp.services.answer_question", return_value={"answer": "a", "sources": []}) as rag:
            self.assertEqual(services.get_chatbot_reply("Frage"), {"answer": "a", "sources": []})
        rag.assert_called_once_with("Frage")
