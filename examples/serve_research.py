"""Read-only local fixture viewer. No database, credentials, or remote requests."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from agent.research_contract import validate_report

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web/research-preview'
DATA = ROOT / 'examples/data'
FILES = {
    '/': (WEB / 'index.html', 'text/html'),
    '/app.js': (WEB / 'app.js', 'text/javascript'),
    '/style.css': (WEB / 'style.css', 'text/css'),
    **{'/data/' + name: (DATA / name, 'application/json' if name.endswith('.json') else 'text/plain')
       for name in ['a_company_report_v1.json', 'a_company_report_v2.json',
                    'a_company_business.md', 'a_company_prices.json']},
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        entry = FILES.get(urlsplit(self.path).path)
        if entry is None:
            self.send_error(404)
            return
        path, mime = entry
        body = path.read_bytes()
        if 'report_v' in path.name:
            validate_report(json.loads(body.decode('utf-8-sig')))
        self.send_response(200)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'")
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Local: http://127.0.0.1:{args.port}/', flush=True)
    server.serve_forever()
