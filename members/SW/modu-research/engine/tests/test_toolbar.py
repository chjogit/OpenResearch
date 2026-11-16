"""v0.30 전문가 모드 도구 모음 — 세 묶음 + 마우스 올림 설명."""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / 'web'
IDS = {'file': ['bNew', 'bExample', 'bOpen', 'bSave'],
       'data': ['bMap', 'bDocs', 'bBroker', 'bCheck'],
       'run': ['bValidate', 'bAgent', 'bRun', 'bCancel']}


class ToolbarGroups(unittest.TestCase):
    def setUp(self):
        self.s = (WEB / 'index.html').read_text(encoding='utf-8')

    def test_groups_hold_same_buttons(self):
        for g, ids in IDS.items():
            blk = self.s[self.s.index(f'class="bgrp g-{g}"'):]
            blk = blk[:blk.index('</div>')]
            self.assertEqual(re.findall(r'<button id="(\w+)"', blk), ids)

    def test_every_button_has_tip_and_no_title(self):
        for ids in IDS.values():
            for i in ids:
                tag = re.search(rf'<button id="{i}"[^>]*>', self.s).group(0)
                self.assertIn('data-tip="', tag)
                self.assertNotIn(' title=', tag)

    def test_run_state_attrs_kept(self):
        self.assertRegex(self.s, r'<button id="bRun" class="primary"')
        self.assertRegex(self.s, r'<button id="bCancel" disabled')

    def test_toolbar_wraps_not_clips(self):
        css = (WEB / 'app.css').read_text(encoding='utf-8')
        tail = css[css.index('v0.30'):]
        self.assertIn('.btns{flex-wrap:wrap', tail)
        self.assertIn('overflow:visible', tail)


if __name__ == '__main__':
    unittest.main()
