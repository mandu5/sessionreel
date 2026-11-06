"""Chapter seeking requires real partial-content responses from the preview server."""

import functools
import runpy
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

Handler = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/serve_site.py"))["RangeRequestHandler"]


@pytest.fixture
def media_url(tmp_path):
    (tmp_path / "demo.mp4").write_bytes(b"0123456789")
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(tmp_path)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/demo.mp4"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.mark.parametrize("range_header, content, content_range", [
    ("bytes=2-5", b"2345", "bytes 2-5/10"),
    ("bytes=6-", b"6789", "bytes 6-9/10"),
    ("bytes=-3", b"789", "bytes 7-9/10"),
    ("bytes=8-99", b"89", "bytes 8-9/10"),
])
def test_media_ranges_return_exact_requested_bytes(media_url, range_header, content, content_range):
    with urlopen(Request(media_url, headers={"Range": range_header}), timeout=5) as response:
        assert response.status == 206
        assert response.headers["Content-Range"] == content_range
        assert response.headers["Accept-Ranges"] == "bytes"
        assert int(response.headers["Content-Length"]) == len(content)
        assert response.read() == content


@pytest.mark.parametrize("range_header", ["bytes=10-", "bytes=6-3", "bytes=-0", "bytes=", "bytes=0-1,4-5"])
def test_invalid_or_unsatisfiable_ranges_do_not_return_the_wrong_video_bytes(media_url, range_header):
    with pytest.raises(HTTPError) as error:
        urlopen(Request(media_url, headers={"Range": range_header}), timeout=5)
    assert error.value.code == 416
    assert error.value.headers["Content-Range"] == "bytes */10"
    assert error.value.read() == b""


def test_head_preserves_range_metadata_without_a_body(media_url):
    with urlopen(Request(media_url, method="HEAD", headers={"Range": "bytes=3-5"}), timeout=5) as response:
        assert response.status == 206
        assert response.headers["Content-Range"] == "bytes 3-5/10"
        assert response.headers["Content-Length"] == "3"
        assert response.read() == b""


def test_normal_and_conditional_downloads_keep_the_original_file(media_url):
    for headers in [{}, {"Range": "bytes=3-5", "If-Range": '"old-version"'}]:
        with urlopen(Request(media_url, headers=headers), timeout=5) as response:
            assert response.status == 200
            assert response.read() == b"0123456789"
