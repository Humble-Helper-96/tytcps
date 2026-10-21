# SPDX-License-Identifier: GPL-3.0-or-later
"""The conf model: unedited lines verbatim, edits only where made."""

import difflib
import unittest

from tests.common import World
from tytcps.backend import codeplug
from tytcps.backend.conf import ConfDocument, format_list, parse_list


class ConfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = World()
        cp, r = codeplug.open_file(cls.w.engine, cls.w.demo_image())
        cls.text = cp.doc.text

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def changed_lines(self, a, b):
        return [l for l in difflib.unified_diff(a.splitlines(), b.splitlines(), n=0, lineterm="")
                if l[:1] in "+-" and not l.startswith(("+++", "---"))]

    def test_roundtrip_is_verbatim(self):
        self.assertEqual(ConfDocument(self.text).render(), self.text)

    def test_one_cell_one_line(self):
        d = ConfDocument(self.text)
        d.tables["Digital"].find(2).cells[14] = "1"
        ch = self.changed_lines(self.text, d.render())
        self.assertEqual(len(ch), 2)
        self.assertIn("TAC_2", ch[0])
        self.assertEqual(d.edited_records(), {("channel", 2)})

    def test_delete_channel_drops_references(self):
        d = ConfDocument(self.text)
        d.delete_rows("Digital", [d.tables["Digital"].find(2)])
        out = ConfDocument(d.render())
        self.assertIsNone(out.tables["Digital"].find(2))
        z = out.tables["Zone"].find(1)
        self.assertNotIn(2, parse_list(z.cells[2]))
        s = out.tables["Scanlist"].find(1)
        self.assertNotIn(2, parse_list(s.cells[5]))

    def test_swap_keeps_references(self):
        d = ConfDocument(self.text)
        a, b = d.tables["Contact"].find(1), d.tables["Contact"].find(2)
        d.swap_numbers("Contact", a, b)
        out = ConfDocument(d.render())
        # TAC_1 still transmits to All_Units, now contact 2.
        self.assertEqual(out.tables["Digital"].find(1).cells[12], "2")
        self.assertEqual(out.name_of("Contact", 2), "All_Units")

    def test_new_table_inserted_in_order(self):
        d = ConfDocument(self.text)
        for r in list(d.rows("Analog")):
            pass
        row = d.add_row("Analog")
        self.assertIsNotNone(row)
        out = ConfDocument(d.render())
        self.assertEqual(len(out.rows("Analog")), len(d.rows("Analog")))

    def test_lists_keep_order(self):
        for text in ("1-2,18,17,7-13,6", "5,4,3", "1", "-"):
            self.assertEqual(format_list(parse_list(text)), text)

    def test_rows_start_with_space(self):
        d = ConfDocument(self.text)
        d.tables["Contact"].rows[0].cells[0] = "10000"
        line = d.render().splitlines()
        self.assertTrue(any(l.startswith(" 10000") for l in line))


if __name__ == "__main__":
    unittest.main()
