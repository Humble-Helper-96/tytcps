# SPDX-License-Identifier: GPL-3.0-or-later
"""The backend against the bundled engine, offline (no radio)."""

import hashlib
import os
import unittest

from tests.common import World
from tytcps.backend import codeplug, keys
from tytcps.backend.engine import load_pin


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()

    def test_engine_is_the_pinned_one(self):
        c = self.w.engine.check()
        self.assertTrue(c.ok, c.problem)
        self.assertEqual(c.info["commit"], load_pin()["commit"])

    def make_keyset(self):
        ks = keys.KeySet()
        for slot, t in ((1, "AES256"), (2, "AES128"), (3, "ARC4")):
            s = ks.slots[slot - 1]
            s.type, s.name, s.key = t, "Demo-%d" % slot, keys.generate(t)
        name, sha = keys.save_new(self.w.engine, ks, self.w.fleet.keys_dir)
        self.w.fleet.set_current(name)
        return name, sha, ks

    def test_keyset_saved_reads_back_identical(self):
        name, sha, ks = self.make_keyset()
        back = keys.load(self.w.engine, self.w.fleet.keys_dir / name)
        self.assertEqual([(s.type, s.name, s.key) for s in back.filled()],
                         [(s.type, s.name, s.key) for s in ks.filled()])
        p = self.w.fleet.keys_dir / name
        self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")
        self.assertFalse([f for f in os.listdir(self.w.fleet.keys_dir) if f.endswith(".bak")])

    def test_import_is_byte_for_byte(self):
        name, sha, _ = self.make_keyset()
        src = self.w.fleet.keys_dir / name
        imp = keys.import_file(self.w.engine, src)
        n2, sha2 = keys.save_new(self.w.engine, imp, self.w.fleet.keys_dir)
        self.assertEqual(sha2, sha)
        self.assertEqual((self.w.fleet.keys_dir / n2).read_bytes(), src.read_bytes())

    def test_preview_one_byte_and_located_error(self):
        self.make_keyset()
        cp, r = codeplug.open_file(self.w.engine, self.w.demo_image())
        row = cp.doc.tables["Digital"].find(2)
        row.cells[14] = "1"
        p, _, _ = codeplug.run_preview(self.w.engine, cp.base, cp.edited_text(),
                                       cp.doc.edited_records(), self.w.fleet.current_path())
        self.assertTrue(p.ok)
        self.assertEqual(p.changed, 1)
        self.assertEqual(p.unexplained, [])
        self.assertEqual(p.records[0]["fields"][0], {"field": "Key", "old": "2", "new": "1"})
        row.cells[14] = "9"
        p, _, _ = codeplug.run_preview(self.w.engine, cp.base, cp.edited_text(),
                                       cp.doc.edited_records(), self.w.fleet.current_path())
        self.assertFalse(p.ok)
        e = p.errors[0]
        self.assertEqual((e["code"], e["section"], e["id"], e["column"]),
                         ("key_slot_empty", "Digital", "2", "Key"))

    def test_type_change_is_one_byte(self):
        """The corrected 6.6 test: Universal -> Basic on one channel."""
        cp, r = codeplug.open_file(self.w.engine, self.w.demo_image())
        cp.doc.tables["Digital"].find(2).cells[13] = "Basic"
        p, _, _ = codeplug.run_preview(self.w.engine, cp.base, cp.edited_text(),
                                       cp.doc.edited_records())
        self.assertTrue(p.ok)
        self.assertEqual(p.changed, 1)

    def test_write_text_leaves_the_radios_id_and_name(self):
        cp, r = codeplug.open_file(self.w.engine, self.w.demo_image())
        text = cp.write_text()
        lines = [l for l in cp.edited_text().split("\n") if not l.startswith(("ID:", "Name:"))]
        self.assertEqual(text.split("\n"), lines)
        self.assertEqual(len(lines), len(cp.edited_text().split("\n")) - 2)
        cp.doc.set_scalar("Name", "Truck_5")            # changed on the General tab: written
        text = cp.write_text()
        self.assertIn("Name: Truck_5", text)
        self.assertNotIn("\nID:", "\n" + text)

    def test_roster_label_edit(self):
        f = self.w.fleet
        with open(f.folder / "radios.tsv", "a") as fh:
            fh.write("00112233445566778899aabbccddeeff\t3102\t-\t2026-10-11T21:14:29-0800\t-\t-\n")
        f.set_label("00112233445566778899aabbccddeeff", "Truck\t3")
        u = f.unit("00112233445566778899aabbccddeeff")
        self.assertEqual((u.radio_id, u.label), ("3102", "Truck 3"))
        f.set_hidden(u.a207, True)
        self.assertTrue(f.unit(u.a207).hidden)


if __name__ == "__main__":
    unittest.main()
