"""Serve the built local site with byte ranges so the demo chapters can seek."""

from __future__ import annotations

import argparse
import functools
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class RangeRequestHandler(SimpleHTTPRequestHandler):
    """Add single byte-range responses to the standard-library static server."""

    def send_head(self):
        self.bytes_left = None
        path = Path(self.translate_path(self.path))
        value = self.headers.get("Range")
        # Ignore conditional ranges: returning the complete representation is safe.
        if not value or self.headers.get("If-Range") or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
        if match and any(match.groups()):
            first, last = match.groups()
            start = int(first) if first else max(0, size - int(last))
            end = min(int(last), size - 1) if first and last else size - 1
        else:
            start, end = size, -1
        if start >= size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        try:
            stream = path.open("rb")
        except OSError:
            self.send_error(404, "File not found")
            return None
        stream.seek(start)
        self.bytes_left = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self.bytes_left))
        self.end_headers()
        return stream

    def copyfile(self, source, outputfile):
        if self.bytes_left is None:
            return super().copyfile(source, outputfile)
        remaining = self.bytes_left
        while remaining > 0:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)
        return None

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=19304)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "build/site")
    args = parser.parse_args()
    if not (args.directory / "index.html").is_file():
        parser.error("Build the site first with python3 scripts/build_site.py")
    handler = functools.partial(RangeRequestHandler, directory=str(args.directory.resolve()))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"SessionReel preview: http://127.0.0.1:{args.port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
