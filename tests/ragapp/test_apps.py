"""Tests for RagappConfig.ready(): stdout/stderr are reconfigured with errors="replace"."""

from unittest import mock

from django.apps import apps
from django.test import SimpleTestCase


class RagappReadyTests(SimpleTestCase):
    def setUp(self):
        self.config = apps.get_app_config("ragapp")

    def test_ready_reconfigures_both_streams(self):
        stdout, stderr = mock.Mock(), mock.Mock()
        with mock.patch("ragapp.apps.sys.stdout", stdout), mock.patch("ragapp.apps.sys.stderr", stderr):
            self.config.ready()
        stdout.reconfigure.assert_called_once_with(errors="replace")
        stderr.reconfigure.assert_called_once_with(errors="replace")

    def test_stream_without_reconfigure_is_ignored(self):
        stderr = mock.Mock()
        with mock.patch("ragapp.apps.sys.stdout", object()), mock.patch("ragapp.apps.sys.stderr", stderr):
            self.config.ready()
        stderr.reconfigure.assert_called_once_with(errors="replace")

    def test_reconfigure_value_error_is_ignored(self):
        stdout = mock.Mock()
        stdout.reconfigure.side_effect = ValueError("closed")
        stderr = mock.Mock()
        with mock.patch("ragapp.apps.sys.stdout", stdout), mock.patch("ragapp.apps.sys.stderr", stderr):
            self.config.ready()
        stderr.reconfigure.assert_called_once_with(errors="replace")
