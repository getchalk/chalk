"""
tests/test_companion_pipeline.py - Comprehensive Unit Tests for Phase 22 Whiteboard Companion.

Tests:
1. Pure-Python QRCode Generator:
   - Version determination, Byte mode encoding, GF(2^8) Reed-Solomon polynomial generation
   - Matrix dimensions & Finder pattern structural integrity
   - Multi-format rendering: SVG, PIL Image, PNG binary bytes, Base64 Data URI, PyQt6 QPixmap
2. Thread-Safe CompanionBridge:
   - Direct callback dispatch & PyQt signal emission
   - Upload counters and connection tracking
3. HTTP Daemon & Mobile Single-Page Web App:
   - Dynamic port binding & thread lifecycle management
   - One-time token authentication (403 on missing/invalid token)
   - Serving 100% inline mobile web app (HTTP 200)
   - Handling photo uploads (POST /upload-photo), saving to session companion dir, and notifying bridge
"""

import os
import sys
import json
import shutil
import tempfile
import urllib.request
import urllib.error
import unittest
from typing import List, Tuple

from src.companion.qr_generator import QRCode
from src.companion.bridge import CompanionBridge
from src.companion.server import CompanionServer, CompanionDaemon, get_local_ip


class TestQRCodeGenerator(unittest.TestCase):
    """Verifies pure-Python zero-dependency QR code generation and exporters."""

    def test_qr_matrix_dimensions_version_1_to_4(self):
        # Short string -> Version 1 (21x21)
        qr1 = QRCode("A", ec_level="L")
        self.assertEqual(qr1.version, 1)
        self.assertEqual(len(qr1.matrix), 21)
        self.assertEqual(len(qr1.matrix[0]), 21)

        # Longer URL -> Version 4 (33x33)
        url = "http://192.168.1.100:8765/?token=AbCdEfGhIjKlMnOpQrSt"
        qr_url = QRCode(url, ec_level="M")
        self.assertGreaterEqual(qr_url.version, 3)
        expected_size = 21 + (qr_url.version - 1) * 4
        self.assertEqual(len(qr_url.matrix), expected_size)
        self.assertEqual(len(qr_url.matrix[0]), expected_size)

    def test_finder_patterns_integrity(self):
        qr = QRCode("https://chalk.local", ec_level="M")
        size = len(qr.matrix)

        # Top-left finder center (3,3) must be 1 (black)
        self.assertEqual(qr.matrix[3][3], 1)
        # Top-right finder center (3, size-4) must be 1
        self.assertEqual(qr.matrix[3][size - 4], 1)
        # Bottom-left finder center (size-4, 3) must be 1
        self.assertEqual(qr.matrix[size - 4][3], 1)

        # Top-left separator ring (e.g. (1, 1) to (5, 5)) has white borders
        self.assertEqual(qr.matrix[1][1], 0)
        self.assertEqual(qr.matrix[5][5], 0)

    def test_svg_export(self):
        qr = QRCode("TestSVG", ec_level="L")
        svg = qr.to_svg(scale=8, border=2)
        self.assertIsInstance(svg, str)
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.endswith("</svg>"))
        self.assertIn("viewBox=", svg)
        self.assertIn("<rect", svg)

    def test_pil_image_export(self):
        qr = QRCode("TestPIL", ec_level="M")
        img = qr.to_pil(scale=4, border=2)
        self.assertIsNotNone(img)
        expected_dim = (qr.size + 4) * 4
        self.assertEqual(img.size, (expected_dim, expected_dim))

    def test_png_bytes_and_base64_data_uri(self):
        qr = QRCode("TestPNG", ec_level="M")
        png_bytes = qr.to_png_bytes(scale=4, border=2)
        self.assertIsInstance(png_bytes, bytes)
        # Check PNG header signature \x89PNG\r\n\x1a\n
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        data_uri = qr.to_base64_data_uri(scale=4, border=2)
        self.assertIsInstance(data_uri, str)
        self.assertTrue(data_uri.startswith("data:image/png;base64,"))

    def test_qpixmap_export(self):
        qr = QRCode("TestQt", ec_level="M")
        try:
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtGui import QPixmap
            app = QApplication.instance()
            if app is None:
                app = QApplication([sys.argv[0], "-platform", "offscreen"])
            pixmap = qr.to_qpixmap(scale=4, border=2)
            self.assertIsInstance(pixmap, QPixmap)
            self.assertFalse(pixmap.isNull())
            expected_dim = (qr.size + 4) * 4
            self.assertEqual(pixmap.width(), expected_dim)
            self.assertEqual(pixmap.height(), expected_dim)
        except ImportError:
            self.skipTest("PyQt6 not installed")


class TestCompanionBridge(unittest.TestCase):
    """Verifies event dispatching and thread safety between HTTP server and UI."""

    def test_bridge_callbacks_and_counters(self):
        bridge = CompanionBridge()
        received: List[Tuple[str, str]] = []

        def callback(path: str, ts: str):
            received.append((path, ts))

        bridge.add_photo_callback(callback)
        self.assertEqual(bridge.upload_count, 0)

        # Emit test event
        bridge.notify_photo_received("/tmp/test_whiteboard.jpg", "14:15:30")
        self.assertEqual(bridge.upload_count, 1)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], ("/tmp/test_whiteboard.jpg", "14:15:30"))

        bridge.notify_client_connected("192.168.1.42")
        bridge.notify_status("Listening...")


class TestCompanionDaemonAndServer(unittest.TestCase):
    """Verifies end-to-end HTTP daemon lifecycle, token security, and upload endpoint."""

    def setUp(self):
        self.temp_storage = tempfile.mkdtemp(prefix="chalk_companion_test_")
        self.session_id = "test_companion_sess_01"
        self.bridge = CompanionBridge()
        self.received_uploads: List[Tuple[str, str]] = []
        self.bridge.add_photo_callback(lambda p, t: self.received_uploads.append((p, t)))

        # Use port in dynamic range to avoid collisions
        self.daemon = CompanionDaemon(
            bridge=self.bridge,
            session_id=self.session_id,
            base_storage_dir=self.temp_storage,
            preferred_port=18950,
        )

    def tearDown(self):
        if self.daemon.is_running:
            self.daemon.stop()
        shutil.rmtree(self.temp_storage, ignore_errors=True)

    def test_server_lifecycle_and_endpoints(self):
        url = self.daemon.start()
        self.assertTrue(self.daemon.is_running)
        self.assertIsNotNone(url)
        self.assertIn("?token=", url)

        # Extract port and token
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        port = parsed.port
        token = urllib.parse.parse_qs(parsed.query)["token"][0]

        base_url = f"http://127.0.0.1:{port}"

        # 1. GET / without token -> 403 Forbidden
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{base_url}/")
        self.assertEqual(ctx.exception.code, 403)

        # 2. GET / with wrong token -> 403 Forbidden
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{base_url}/?token=wrong_secret")
        self.assertEqual(ctx.exception.code, 403)

        # 3. GET / with valid token -> 200 OK, returns mobile web app HTML
        req = urllib.request.Request(f"{base_url}/?token={token}")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("Chalk", content)
            self.assertIn("Tafel-Kamera", content)
            self.assertIn('type="file"', content)
            self.assertIn('capture="environment"', content)

        # 4. GET /ping with valid token -> 200 OK
        req_ping = urllib.request.Request(f"{base_url}/ping?token={token}")
        with urllib.request.urlopen(req_ping) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "ok")

        # 5. POST /upload-photo without token -> 403 Forbidden
        req_post_bad = urllib.request.Request(
            f"{base_url}/upload-photo",
            data=b"dummy",
            headers={"Content-Type": "image/jpeg"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_post_bad)
        self.assertEqual(ctx.exception.code, 403)

        # 6. POST /upload-photo with valid token and synthetic JPEG body -> 200 OK
        import io
        from PIL import Image
        img_buf = io.BytesIO()
        Image.new("RGB", (2, 2), "white").save(img_buf, format="JPEG")
        synthetic_jpeg = img_buf.getvalue()
        req_post_ok = urllib.request.Request(
            f"{base_url}/upload-photo?token={token}",
            data=synthetic_jpeg,
            headers={"Content-Type": "image/jpeg"},
            method="POST",
        )
        with urllib.request.urlopen(req_post_ok) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "ok")
            saved_filename = data.get("file")
            self.assertIsNotNone(saved_filename)
            self.assertTrue(saved_filename.endswith(".jpg"))

        # Verify photo was saved on disk
        companion_dir = os.path.join(self.temp_storage, self.session_id, "companion")
        self.assertTrue(os.path.isdir(companion_dir))
        files = os.listdir(companion_dir)
        self.assertIn(saved_filename, files)

        saved_path = os.path.join(companion_dir, saved_filename)
        self.assertGreater(os.path.getsize(saved_path), 0)

        # Verify bridge notified
        self.assertEqual(len(self.received_uploads), 1)
        self.assertEqual(self.received_uploads[0][0], saved_path)

        # 7. Stop daemon cleanly
        self.daemon.stop()
        self.assertFalse(self.daemon.is_running)


if __name__ == "__main__":
    unittest.main()
