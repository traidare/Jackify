"""
Nexus OAuth callback: _generate_self_signed_cert, _create_callback_handler, _wait_for_callback.
"""

import os
import time
import logging
import tempfile
import urllib.parse
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class NexusOAuthCallbackMixin:
    """Mixin providing callback server and wait logic for NexusOAuthService."""

    def _generate_self_signed_cert(self) -> Tuple[Optional[str], Optional[str]]:
        """Generate self-signed certificate for HTTPS localhost. Returns (cert_file_path, key_file_path) or (None, None)."""
        redirect_host = getattr(self, 'REDIRECT_HOST', '127.0.0.1')
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
            import datetime
            import ipaddress
            logger.info("Generating self-signed certificate for OAuth callback")
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Jackify"),
                x509.NameAttribute(NameOID.COMMON_NAME, redirect_host),
            ])
            cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
                private_key.public_key()
            ).serial_number(x509.random_serial_number()).not_valid_before(
                datetime.datetime.now(datetime.UTC)
            ).not_valid_after(
                datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)
            ).add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPv4Address(redirect_host))]),
                critical=False,
            ).sign(private_key, hashes.SHA256())
            temp_dir = tempfile.mkdtemp()
            cert_file = os.path.join(temp_dir, "oauth_cert.pem")
            key_file = os.path.join(temp_dir, "oauth_key.pem")
            with open(cert_file, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
            with open(key_file, "wb") as f:
                f.write(private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            return cert_file, key_file
        except ImportError:
            logger.error("cryptography package not installed - required for OAuth")
            return None, None
        except Exception as e:
            logger.error("Failed to generate SSL certificate: %s", e)
            return None, None

    def _create_callback_handler(self):
        """Create HTTP request handler class for OAuth callback."""
        service = self
        class OAuthCallbackHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                logger.debug("OAuth callback: %s", format % args)
            def do_GET(self):
                logger.info("OAuth callback received: %s", self.path)
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                if parsed.path == '/favicon.ico':
                    self.send_response(404)
                    self.end_headers()
                    return
                if 'code' in params:
                    service._auth_code = params['code'][0]
                    service._auth_state = params.get('state', [None])[0]
                    logger.info("OAuth authorization code received: %s...", service._auth_code[:10])
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    html = """<html><head><title>Authorization Successful</title></head><body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;"><h1>Authorization Successful!</h1><p>You can close this window and return to Jackify.</p><script>setTimeout(function() { window.close(); }, 3000);</script></body></html>"""
                    self.wfile.write(html.encode())
                elif 'error' in params:
                    service._auth_error = params['error'][0]
                    error_desc = params.get('error_description', ['Unknown error'])[0]
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    html = f"<html><head><title>Authorization Failed</title></head><body style='font-family: Arial, sans-serif; text-align: center; padding: 50px;'><h1>Authorization Failed</h1><p>Error: {service._auth_error}</p><p>{error_desc}</p><p>You can close this window and try again in Jackify.</p></body></html>"
                    self.wfile.write(html.encode())
                else:
                    logger.warning("OAuth callback with no code or error: %s", params)
                    self.send_response(400)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    html = "<html><head><title>Invalid Request</title></head><body style='font-family: Arial, sans-serif; text-align: center; padding: 50px;'><h1>Invalid OAuth Callback</h1><p>You can close this window.</p></body></html>"
                    self.wfile.write(html.encode())
                service._server_done.set()
                logger.debug("OAuth callback handler signaled server to shut down")
        return OAuthCallbackHandler

    def _wait_for_callback(self) -> bool:
        """Wait for OAuth callback via jackify:// protocol handler. Returns True if callback received."""
        callback_file = Path.home() / ".config" / "jackify" / "oauth_callback.tmp"
        if callback_file.exists():
            callback_file.unlink()
        logger.info("Waiting for OAuth callback via jackify:// protocol")
        start_time = time.time()
        last_reminder = 0
        while (time.time() - start_time) < self.CALLBACK_TIMEOUT:
            if callback_file.exists():
                try:
                    lines = callback_file.read_text().strip().split('\n')
                    if len(lines) >= 2:
                        self._auth_code = lines[0]
                        self._auth_state = lines[1]
                        logger.info("OAuth callback received: code=%s...", self._auth_code[:10])
                        callback_file.unlink()
                        return True
                except Exception as e:
                    logger.error("Failed to read callback file: %s", e)
                    return False
            elapsed = time.time() - start_time
            if elapsed - last_reminder > 30:
                logger.info("Still waiting for OAuth callback... (%ss elapsed)", int(elapsed))
                if elapsed > 60:
                    logger.warning(
                        "If you see a blank browser tab, check for browser notifications asking to "
                        "'Open Jackify', or use 'Paste callback URL' in Jackify to paste the URL from the address bar"
                    )
                last_reminder = elapsed
            time.sleep(0.5)
        logger.error("OAuth callback timeout after %s seconds", self.CALLBACK_TIMEOUT)
        logger.error(
            "Protocol handler may not be working. Check:\n"
            "  1. Browser asked 'Open Jackify?' and you clicked Allow\n"
            "  2. No popup blocker notifications\n"
            "  3. Desktop file exists: ~/.local/share/applications/com.jackify.app.desktop"
        )
        return False
