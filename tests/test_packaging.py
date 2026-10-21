# SPDX-License-Identifier: GPL-3.0-or-later
"""TYTcps installed as a Flatpak: where it looks for things."""

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tytcps.backend import paths, usb
from tytcps.ui import firstrun

REPO = Path(__file__).resolve().parent.parent
RULE = ('SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="df11", '
        'MODE="0660", GROUP="plugdev", TAG+="uaccess"')


class FleetFolder(unittest.TestCase):
    def test_checkout_follows_xdg_data_home(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/x/data"}, clear=False):
            os.environ.pop("FLATPAK_ID", None)
            self.assertEqual(paths.default_fleet_folder(), Path("/x/data/tytcps"))

    def test_flatpak_keeps_the_folder_a_checkout_uses(self):
        env = {"FLATPAK_ID": "io.example.TYTcps", "HOME": "/home/u",
               "XDG_DATA_HOME": "/home/u/.var/app/io.example.TYTcps/data"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("HOST_XDG_DATA_HOME", None)
            self.assertEqual(paths.default_fleet_folder(), Path("/home/u/.local/share/tytcps"))
            os.environ["HOST_XDG_DATA_HOME"] = "/home/u/data"
            self.assertEqual(paths.default_fleet_folder(), Path("/home/u/data/tytcps"))


class UsbRule(unittest.TestCase):
    def test_flatpak_looks_in_the_computers_etc(self):
        with tempfile.TemporaryDirectory() as host, tempfile.TemporaryDirectory() as sandbox:
            Path(host, "70-tytcps.rules").write_text(RULE + "\n")
            with mock.patch.object(usb, "FLATPAK_RULE_DIRS", [host]), \
                    mock.patch.object(usb, "RULE_DIRS", [sandbox]):
                with mock.patch.dict(os.environ, {"FLATPAK_ID": "io.example.TYTcps"}):
                    rule = usb.find_rule()
                    self.assertIsNotNone(rule)
                    self.assertTrue(rule.uaccess)
                os.environ.pop("FLATPAK_ID", None)
                self.assertIsNone(usb.find_rule())

    def test_uaccess_counts_only_before_73_seat_late(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(usb, "RULE_DIRS", [d]):
                os.environ.pop("FLATPAK_ID", None)
                Path(d, "99-late.rules").write_text(RULE + "\n")
                rule = usb.find_rule()
                self.assertFalse(rule.uaccess)
                self.assertEqual(rule.group, "plugdev")
                Path(d, "99-late.rules").unlink()
                Path(d, "70-tytcps.rules").write_text(RULE + "\n")
                self.assertTrue(usb.find_rule().uaccess)

    def test_flatpak_command_carries_the_rule_text(self):
        with mock.patch.dict(os.environ, {"FLATPAK_ID": "io.example.TYTcps"}):
            cmds = firstrun.terminal_rule_commands()
        self.assertEqual(cmds[0], "echo '%s' | sudo tee /etc/udev/rules.d/70-tytcps.rules" % RULE)
        self.assertTrue(all(c.startswith(("echo ", "sudo ")) for c in cmds))
        self.assertFalse(any("/app/" in c or "pkexec" in c for c in cmds))

    def test_appimage_command_carries_the_rule_text(self):
        with mock.patch.dict(os.environ, {"APPIMAGE": "/home/u/TYTcps.AppImage"}):
            os.environ.pop("FLATPAK_ID", None)
            cmds = firstrun.terminal_rule_commands()
        self.assertTrue(cmds[0].startswith("echo '%s' | sudo tee " % RULE))

    def test_checkout_command_installs_the_file(self):
        os.environ.pop("FLATPAK_ID", None)
        os.environ.pop("APPIMAGE", None)
        cmds = firstrun.terminal_rule_commands()
        self.assertTrue(cmds[0].startswith("sudo install -m 644 "))
        self.assertTrue(cmds[0].endswith("/etc/udev/rules.d/70-tytcps.rules"))


class Manifest(unittest.TestCase):
    def test_app_id_agrees(self):
        appid = re.search(r"^APPID\s*\?=\s*(\S+)", (REPO / "Makefile").read_text(), re.M).group(1)
        manifest = REPO / "packaging" / "flatpak" / ("%s.yml" % appid)
        self.assertTrue(manifest.is_file(), manifest)
        self.assertIn("id: %s\n" % appid, manifest.read_text())
        self.assertIn("<id>@APPID@</id>", (REPO / "packaging" / "tytcps.metainfo.xml").read_text())


if __name__ == "__main__":
    unittest.main()
