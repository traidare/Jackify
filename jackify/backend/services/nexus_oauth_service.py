#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nexus OAuth Service
Handles OAuth 2.0 authentication flow with Nexus Mods using PKCE
"""

import os
import base64
import hashlib
import secrets
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import json
import threading
import ssl
import tempfile
import logging
import time
import subprocess
from typing import Optional, Tuple, Dict

logger = logging.getLogger(__name__)


class NexusOAuthService:
    """
    Handles OAuth 2.0 authentication with Nexus Mods
    Uses PKCE flow with system browser and localhost callback
    """

    # OAuth Configuration
    CLIENT_ID = "jackify"
    AUTH_URL = "https://users.nexusmods.com/oauth/authorize"
    TOKEN_URL = "https://users.nexusmods.com/oauth/token"
    USERINFO_URL = "https://users.nexusmods.com/oauth/userinfo"
    SCOPES = "public openid profile"

    # Redirect configuration (custom protocol scheme - no SSL cert needed!)
    # Requires jackify:// protocol handler to be registered with OS
    REDIRECT_URI = "jackify://oauth/callback"

    # Callback timeout (5 minutes)
    CALLBACK_TIMEOUT = 300

    def __init__(self):
        """Initialize OAuth service"""
        self._auth_code = None
        self._auth_state = None
        self._auth_error = None
        self._server_done = threading.Event()

        # Ensure jackify:// protocol is registered on first use
        self._ensure_protocol_registered()

    def _generate_pkce_params(self) -> Tuple[str, str, str]:
        """
        Generate PKCE code verifier, challenge, and state

        Returns:
            Tuple of (code_verifier, code_challenge, state)
        """
        # Generate code verifier (43-128 characters, base64url encoded)
        code_verifier = base64.urlsafe_b64encode(
            os.urandom(32)
        ).decode('utf-8').rstrip('=')

        # Generate code challenge (SHA256 hash of verifier, base64url encoded)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)

        return code_verifier, code_challenge, state

    def _ensure_protocol_registered(self) -> bool:
        """
        Ensure jackify:// protocol is registered with the OS

        Returns:
            True if registration successful or already registered
        """
        import subprocess
        import sys
        from pathlib import Path

        if not sys.platform.startswith('linux'):
            logger.debug("Protocol registration only needed on Linux")
            return True

        try:
            # Ensure desktop file exists and has correct Exec path
            desktop_file = Path.home() / ".local" / "share" / "applications" / "com.jackify.app.desktop"

            # Get environment for AppImage detection
            env = os.environ
            
            # Determine executable path (DEV mode vs AppImage)
            # Check multiple indicators for AppImage execution
            is_appimage = (
                'APPIMAGE' in env or              # AppImage environment variable
                'APPDIR' in env or               # AppImage directory variable
                (sys.argv[0] and sys.argv[0].endswith('.AppImage'))  # Executable name
            )
            
            if is_appimage:
                # Running from AppImage - use the AppImage path directly
                # CRITICAL: Never use -m flag in AppImage mode - it causes __main__.py windows
                if 'APPIMAGE' in env:
                    # APPIMAGE env var gives us the exact path to the AppImage
                    exec_path = env['APPIMAGE']
                    logger.info(f"Using APPIMAGE env var: {exec_path}")
                elif sys.argv[0] and Path(sys.argv[0]).exists():
                    # Use sys.argv[0] if it's a valid path
                    exec_path = str(Path(sys.argv[0]).resolve())
                    logger.info(f"Using resolved sys.argv[0]: {exec_path}")
                else:
                    # Fallback to sys.argv[0] as-is
                    exec_path = sys.argv[0]
                    logger.warning(f"Using sys.argv[0] as fallback: {exec_path}")
            else:
                # Running from source (DEV mode)
                # Need to ensure we run from the correct directory
                src_dir = Path(__file__).parent.parent.parent.parent  # Go up to src/
                # Use bash -c with proper quoting for paths with spaces
                exec_path = f'bash -c \'cd "{src_dir}" && "{sys.executable}" -m jackify.frontends.gui "$@"\' --'
                logger.info(f"DEV mode exec path: {exec_path}")
                logger.info(f"Source directory: {src_dir}")

            # Check if desktop file needs creation or update
            needs_update = False
            if not desktop_file.exists():
                needs_update = True
                logger.info("Creating desktop file for protocol handler")
            else:
                # Check if Exec path matches current mode
                current_content = desktop_file.read_text()
                # Check for both quoted (AppImage) and unquoted (DEV mode with bash -c) formats
                if is_appimage:
                    expected_exec = f'Exec="{exec_path}" %u'
                else:
                    expected_exec = f"Exec={exec_path} %u"

                if expected_exec not in current_content:
                    needs_update = True
                    logger.info(f"Updating desktop file with new Exec path: {exec_path}")

                # Explicitly detect and fix malformed entries (unquoted paths with spaces)
                # Check if any Exec line exists without quotes but contains spaces
                if is_appimage and ' ' in exec_path:
                    import re
                    # Look for Exec=<path with spaces> without quotes
                    if re.search(r'Exec=[^"]\S*\s+\S*\.AppImage', current_content):
                        needs_update = True
                        logger.info("Fixing malformed desktop file (unquoted path with spaces)")

            if needs_update:
                desktop_file.parent.mkdir(parents=True, exist_ok=True)

                # Build desktop file content with proper working directory
                if is_appimage:
                    # AppImage - quote path to handle spaces
                    desktop_content = f"""[Desktop Entry]
Type=Application
Name=Jackify
Comment=Wabbajack modlist manager for Linux
Exec="{exec_path}" %u
Icon=com.jackify.app
Terminal=false
Categories=Game;Utility;
MimeType=x-scheme-handler/jackify;
"""
                else:
                    # DEV mode - exec_path already contains bash -c with proper quoting
                    src_dir = Path(__file__).parent.parent.parent.parent  # Go up to src/
                    desktop_content = f"""[Desktop Entry]
Type=Application
Name=Jackify
Comment=Wabbajack modlist manager for Linux
Exec={exec_path} %u
Icon=com.jackify.app
Terminal=false
Categories=Game;Utility;
MimeType=x-scheme-handler/jackify;
Path={src_dir}
"""
                
                desktop_file.write_text(desktop_content)
                logger.info(f"Desktop file written: {desktop_file}")
                logger.info(f"Exec path: {exec_path}")
                logger.info(f"AppImage mode: {is_appimage}")

            # Always ensure full registration (don't trust xdg-settings alone)
            # PopOS/Ubuntu need mimeapps.list even if xdg-settings says registered
            logger.info("Registering jackify:// protocol handler")

            # Update MIME cache (required for Firefox dialog)
            apps_dir = Path.home() / ".local" / "share" / "applications"
            subprocess.run(
                ['update-desktop-database', str(apps_dir)],
                capture_output=True,
                timeout=10
            )

            # Set as default handler using xdg-mime (Firefox compatibility)
            subprocess.run(
                ['xdg-mime', 'default', 'com.jackify.app.desktop', 'x-scheme-handler/jackify'],
                capture_output=True,
                timeout=10
            )

            # Also use xdg-settings as backup (some systems need both)
            subprocess.run(
                ['xdg-settings', 'set', 'default-url-scheme-handler', 'jackify', 'com.jackify.app.desktop'],
                capture_output=True,
                timeout=10
            )

            # Manually ensure entry in mimeapps.list (PopOS/Ubuntu require this for GIO)
            mimeapps_path = Path.home() / ".config" / "mimeapps.list"
            try:
                # Read existing content
                if mimeapps_path.exists():
                    content = mimeapps_path.read_text()
                else:
                    mimeapps_path.parent.mkdir(parents=True, exist_ok=True)
                    content = "[Default Applications]\n"

                # Add jackify handler if not present
                if 'x-scheme-handler/jackify=' not in content:
                    if '[Default Applications]' not in content:
                        content = "[Default Applications]\n" + content

                    # Insert after [Default Applications] line
                    lines = content.split('\n')
                    for i, line in enumerate(lines):
                        if line.strip() == '[Default Applications]':
                            lines.insert(i + 1, 'x-scheme-handler/jackify=com.jackify.app.desktop')
                            break

                    content = '\n'.join(lines)
                    mimeapps_path.write_text(content)
                    logger.info("Added jackify handler to mimeapps.list")
            except Exception as e:
                logger.warning(f"Failed to update mimeapps.list: {e}")

            logger.info("jackify:// protocol registered successfully")
            return True

        except Exception as e:
            logger.warning(f"Failed to register jackify:// protocol: {e}")
            return False

    def _generate_self_signed_cert(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate self-signed certificate for HTTPS localhost

        Returns:
            Tuple of (cert_file_path, key_file_path) or (None, None) on failure
        """
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
            import datetime
            import ipaddress

            logger.info("Generating self-signed certificate for OAuth callback")

            # Generate private key
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )

            # Create certificate
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Jackify"),
                x509.NameAttribute(NameOID.COMMON_NAME, self.REDIRECT_HOST),
            ])

            cert = x509.CertificateBuilder().subject_name(
                subject
            ).issuer_name(
                issuer
            ).public_key(
                private_key.public_key()
            ).serial_number(
                x509.random_serial_number()
            ).not_valid_before(
                datetime.datetime.now(datetime.UTC)
            ).not_valid_after(
                datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)
            ).add_extension(
                x509.SubjectAlternativeName([
                    x509.IPAddress(ipaddress.IPv4Address(self.REDIRECT_HOST)),
                ]),
                critical=False,
            ).sign(private_key, hashes.SHA256())

            # Save to temp files
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
            logger.error(f"Failed to generate SSL certificate: {e}")
            return None, None

    def _build_authorization_url(self, code_challenge: str, state: str) -> str:
        """
        Build OAuth authorization URL

        Args:
            code_challenge: PKCE code challenge
            state: CSRF protection state

        Returns:
            Authorization URL
        """
        params = {
            'response_type': 'code',
            'client_id': self.CLIENT_ID,
            'redirect_uri': self.REDIRECT_URI,
            'scope': self.SCOPES,
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
            'state': state
        }

        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    def _create_callback_handler(self):
        """Create HTTP request handler class for OAuth callback"""
        service = self

        class OAuthCallbackHandler(BaseHTTPRequestHandler):
            """HTTP request handler for OAuth callback"""

            def log_message(self, format, *args):
                """Log OAuth callback requests"""
                logger.debug(f"OAuth callback: {format % args}")

            def do_GET(self):
                """Handle GET request from OAuth redirect"""
                logger.info(f"OAuth callback received: {self.path}")

                # Parse query parameters
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)

                # Ignore favicon and other non-OAuth requests
                if parsed.path == '/favicon.ico':
                    self.send_response(404)
                    self.end_headers()
                    return

                if 'code' in params:
                    service._auth_code = params['code'][0]
                    service._auth_state = params.get('state', [None])[0]
                    logger.info(f"OAuth authorization code received: {service._auth_code[:10]}...")

                    # Send success response
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()

                    html = """
                    <html>
                    <head><title>Authorization Successful</title></head>
                    <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                        <h1>Authorization Successful!</h1>
                        <p>You can close this window and return to Jackify.</p>
                        <script>setTimeout(function() { window.close(); }, 3000);</script>
                    </body>
                    </html>
                    """
                    self.wfile.write(html.encode())

                elif 'error' in params:
                    service._auth_error = params['error'][0]
                    error_desc = params.get('error_description', ['Unknown error'])[0]

                    # Send error response
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()

                    html = f"""
                    <html>
                    <head><title>Authorization Failed</title></head>
                    <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                        <h1>Authorization Failed</h1>
                        <p>Error: {service._auth_error}</p>
                        <p>{error_desc}</p>
                        <p>You can close this window and try again in Jackify.</p>
                    </body>
                    </html>
                    """
                    self.wfile.write(html.encode())
                else:
                    # Unexpected callback format
                    logger.warning(f"OAuth callback with no code or error: {params}")
                    self.send_response(400)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    html = """
                    <html>
                    <head><title>Invalid Request</title></head>
                    <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                        <h1>Invalid OAuth Callback</h1>
                        <p>You can close this window.</p>
                    </body>
                    </html>
                    """
                    self.wfile.write(html.encode())

                # Signal server to shut down
                service._server_done.set()
                logger.debug("OAuth callback handler signaled server to shut down")

        return OAuthCallbackHandler

    def _wait_for_callback(self) -> bool:
        """
        Wait for OAuth callback via jackify:// protocol handler

        Returns:
            True if callback received, False on timeout
        """
        from pathlib import Path
        import time

        callback_file = Path.home() / ".config" / "jackify" / "oauth_callback.tmp"

        # Delete any old callback file
        if callback_file.exists():
            callback_file.unlink()

        logger.info("Waiting for OAuth callback via jackify:// protocol")

        # Poll for callback file with periodic user feedback
        start_time = time.time()
        last_reminder = 0
        while (time.time() - start_time) < self.CALLBACK_TIMEOUT:
            if callback_file.exists():
                try:
                    # Read callback data
                    lines = callback_file.read_text().strip().split('\n')
                    if len(lines) >= 2:
                        self._auth_code = lines[0]
                        self._auth_state = lines[1]
                        logger.info(f"OAuth callback received: code={self._auth_code[:10]}...")

                        # Clean up
                        callback_file.unlink()
                        return True
                except Exception as e:
                    logger.error(f"Failed to read callback file: {e}")
                    return False

            # Show periodic reminder about protocol handler
            elapsed = time.time() - start_time
            if elapsed - last_reminder > 30:  # Every 30 seconds
                logger.info(f"Still waiting for OAuth callback... ({int(elapsed)}s elapsed)")
                if elapsed > 60:
                    logger.warning(
                        "If you see a blank browser tab or popup blocker, "
                        "check for browser notifications asking to 'Open Jackify'"
                    )
                last_reminder = elapsed

            time.sleep(0.5)  # Poll every 500ms

        logger.error(f"OAuth callback timeout after {self.CALLBACK_TIMEOUT} seconds")
        logger.error(
            "Protocol handler may not be working. Check:\n"
            "  1. Browser asked 'Open Jackify?' and you clicked Allow\n"
            "  2. No popup blocker notifications\n"
            "  3. Desktop file exists: ~/.local/share/applications/com.jackify.app.desktop"
        )
        return False

    def _send_desktop_notification(self, title: str, message: str):
        """
        Send desktop notification if available

        Args:
            title: Notification title
            message: Notification message
        """
        try:
            # Try notify-send (Linux)
            subprocess.run(
                ['notify-send', title, message],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    def _exchange_code_for_token(
        self,
        auth_code: str,
        code_verifier: str
    ) -> Optional[Dict]:
        """
        Exchange authorization code for access token

        Args:
            auth_code: Authorization code from callback
            code_verifier: PKCE code verifier

        Returns:
            Token response dict or None on failure
        """
        data = {
            'grant_type': 'authorization_code',
            'client_id': self.CLIENT_ID,
            'redirect_uri': self.REDIRECT_URI,
            'code': auth_code,
            'code_verifier': code_verifier
        }

        try:
            response = requests.post(self.TOKEN_URL, data=data, timeout=10)

            if response.status_code == 200:
                token_data = response.json()
                logger.info("Successfully exchanged authorization code for token")
                return token_data
            else:
                logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                return None

        except requests.RequestException as e:
            logger.error(f"Token exchange request failed: {e}")
            return None

    def refresh_token(self, refresh_token: str) -> Optional[Dict]:
        """
        Refresh an access token using refresh token

        Args:
            refresh_token: Refresh token from previous authentication

        Returns:
            New token response dict or None on failure
        """
        data = {
            'grant_type': 'refresh_token',
            'client_id': self.CLIENT_ID,
            'refresh_token': refresh_token
        }

        try:
            response = requests.post(self.TOKEN_URL, data=data, timeout=10)

            if response.status_code == 200:
                token_data = response.json()
                logger.info("Successfully refreshed access token")
                return token_data
            else:
                logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
                return None

        except requests.RequestException as e:
            logger.error(f"Token refresh request failed: {e}")
            return None

    def get_user_info(self, access_token: str) -> Optional[Dict]:
        """
        Get user information using access token

        Args:
            access_token: OAuth access token

        Returns:
            User info dict or None on failure
        """
        headers = {
            'Authorization': f'Bearer {access_token}'
        }

        try:
            response = requests.get(self.USERINFO_URL, headers=headers, timeout=10)

            if response.status_code == 200:
                user_info = response.json()
                logger.info(f"Retrieved user info for: {user_info.get('name', 'unknown')}")
                return user_info
            else:
                logger.error(f"User info request failed: {response.status_code}")
                return None

        except requests.RequestException as e:
            logger.error(f"User info request failed: {e}")
            return None

    def authorize(self, show_browser_message_callback=None) -> Optional[Dict]:
        """
        Perform full OAuth authorization flow

        Args:
            show_browser_message_callback: Optional callback to display message about browser opening

        Returns:
            Token response dict or None on failure
        """
        logger.info("Starting Nexus OAuth authorization flow")

        # Reset state
        self._auth_code = None
        self._auth_state = None
        self._auth_error = None
        self._server_done.clear()

        # Generate PKCE parameters
        code_verifier, code_challenge, state = self._generate_pkce_params()
        logger.debug(f"Generated PKCE parameters (state: {state[:10]}...)")

        # Build authorization URL
        auth_url = self._build_authorization_url(code_challenge, state)

        # Open browser
        logger.info("Opening browser for authorisation")

        try:
            # When running from AppImage, we need to clean the environment to avoid
            # library conflicts with system tools (xdg-open, kde-open, etc.)
            import os
            import subprocess

            env = os.environ.copy()

            # Remove AppImage-specific environment variables that can cause conflicts
            # These variables inject AppImage's bundled libraries into child processes
            appimage_vars = [
                'LD_LIBRARY_PATH',
                'PYTHONPATH',
                'PYTHONHOME',
                'QT_PLUGIN_PATH',
                'QML2_IMPORT_PATH',
            ]

            # Check if we're running from AppImage
            if 'APPIMAGE' in env or 'APPDIR' in env:
                logger.debug("Running from AppImage - cleaning environment for browser launch")
                for var in appimage_vars:
                    if var in env:
                        del env[var]
                        logger.debug(f"Removed {var} from browser environment")

            # Use Popen instead of run to avoid waiting for browser to close
            # xdg-open may not return until the browser closes, which could be never
            try:
                process = subprocess.Popen(
                    ['xdg-open', auth_url],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True  # Detach from parent process
                )
                # Give it a moment to fail if it's going to fail
                import time
                time.sleep(0.5)

                # Check if process is still running or has exited successfully
                poll_result = process.poll()
                if poll_result is None:
                    # Process still running - browser is opening/open
                    logger.info("Browser opened successfully via xdg-open (process running)")
                    browser_opened = True
                elif poll_result == 0:
                    # Process exited successfully
                    logger.info("Browser opened successfully via xdg-open (exit code 0)")
                    browser_opened = True
                else:
                    # Process exited with error
                    logger.warning(f"xdg-open exited with code {poll_result}, trying webbrowser module")
                    if webbrowser.open(auth_url):
                        logger.info("Browser opened successfully via webbrowser module")
                        browser_opened = True
                    else:
                        logger.warning("webbrowser.open returned False")
                        browser_opened = False
            except FileNotFoundError:
                # xdg-open not found - try webbrowser module
                logger.warning("xdg-open not found, trying webbrowser module")
                if webbrowser.open(auth_url):
                    logger.info("Browser opened successfully via webbrowser module")
                    browser_opened = True
                else:
                    logger.warning("webbrowser.open returned False")
                    browser_opened = False
        except Exception as e:
            logger.error(f"Error opening browser: {e}")
            browser_opened = False

        # Send desktop notification
        self._send_desktop_notification(
            "Jackify - Nexus Authorisation",
            "Please check your browser to authorise Jackify"
        )

        # Show message via callback if provided (AFTER browser opens)
        if show_browser_message_callback:
            if browser_opened:
                show_browser_message_callback(
                    "Browser opened for Nexus authorisation.\n\n"
                    "After clicking 'Authorize', your browser may ask to\n"
                    "open Jackify or show a popup blocker notification.\n\n"
                    "Please click 'Open' or 'Allow' to complete authorization."
                )
            else:
                show_browser_message_callback(
                    f"Could not open browser automatically.\n\n"
                    f"Please open this URL manually:\n{auth_url}"
                )

        # Wait for callback via jackify:// protocol
        if not self._wait_for_callback():
            return None

        # Check for errors
        if self._auth_error:
            logger.error(f"Authorization failed: {self._auth_error}")
            return None

        if not self._auth_code:
            logger.error("No authorization code received")
            return None

        # Verify state matches
        if self._auth_state != state:
            logger.error("State mismatch - possible CSRF attack")
            return None

        logger.info("Authorization code received, exchanging for token")

        # Exchange code for token
        token_data = self._exchange_code_for_token(self._auth_code, code_verifier)

        if token_data:
            logger.info("OAuth authorization flow completed successfully")
        else:
            logger.error("Failed to exchange authorization code for token")

        return token_data
