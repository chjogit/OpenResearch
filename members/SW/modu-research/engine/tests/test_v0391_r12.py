"""v0.39.1 R12: Claude 모델에는 temperature 를 보내지 않고, 로컬 모델에는 그대로 보낸다. 실제 네트워크는 쓰지 않는다."""
import json, os, unittest
from unittest import mock


class _Resp:
    def __init__(self, text): self._t = text
    def read(self): return json.dumps({'choices': [{'message': {'content': self._t}}]}).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False


class R12(unittest.TestCase):
    def _sent(self, model, fn):
        seen = {}
        def fake(req, timeout=None):
            seen['body'] = json.loads(req.data.decode()); seen['auth'] = req.headers.get('Authorization')
            return _Resp('{"card": null, "rewrite": null, "why": "x"}')
        env = {'MODU_NODES_LLM_URL': 'http://x/v1', 'MODU_NODES_LLM_MODEL': model, 'MODU_NODES_LLM_KEY': 'k'}
        with mock.patch.dict(os.environ, env), mock.patch('urllib.request.urlopen', fake):
            fn()
        return seen['body']

    def test_guide_claude_no_temperature(self):
        from mrn import guide
        b = self._sent('claude-sonnet-5-5', lambda: guide._call_model('p'))
        self.assertNotIn('temperature', b); self.assertEqual(b['max_tokens'], 1024); self.assertEqual(b['model'], 'claude-sonnet-5-5')

    def test_guide_local_keeps_temperature(self):
        from mrn import guide
        b = self._sent('exaone3.5:7.8b', lambda: guide._call_model('p'))
        self.assertEqual(b['temperature'], 0); self.assertEqual(b['max_tokens'], 1024)

    def test_planner_claude_no_temperature(self):
        from mrn import planner
        b = self._sent('claude-sonnet-5-5', lambda: planner.model_plan('삼성전자 실적', None))
        self.assertNotIn('temperature', b); self.assertEqual(b['max_tokens'], 1024)


if __name__ == '__main__':
    unittest.main()
