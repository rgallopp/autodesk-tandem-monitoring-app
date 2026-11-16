"""Offline tests only. Real HTTP is forbidden throughout this test process."""

from unittest.mock import patch

_network_block = patch("requests.sessions.Session.request", side_effect=AssertionError("Offline tests forbid real HTTP"))
_network_block.start()
