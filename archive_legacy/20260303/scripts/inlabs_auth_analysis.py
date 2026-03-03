#!/usr/bin/env python3
"""
INLabs Authentication System Analysis
Tests authentication flow, cookies, session persistence, and security mechanisms.
"""
from __future__ import annotations

import time
import json
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Any
import requests
from urllib.parse import urljoin, parse_qs, urlparse
import re

# Configuration
BASE_URL = "https://inlabs.in.gov.br"
LOGIN_URL = f"{BASE_URL}/logar.php"  # Corrected login URL
INDEX_URL = f"{BASE_URL}/index.php?p="
LOGOUT_URL = f"{BASE_URL}/logout.php"

# Credentials from environment (hardcoded for testing)
CREDENTIALS = {
    "email": "fgamajr@gmail.com",
    "password": "kqg8YDZ2eya3exq_wev"
}


@dataclass
class AuthTestResult:
    """Container for authentication test results."""
    test_name: str
    timestamp: str
    success: bool
    status_code: int | None = None
    cookies: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    response_time_ms: float = 0.0
    notes: list[str] = field(default_factory=list)
    html_snippet: str = ""


class INLabsAuthAnalyzer:
    """Analyzer for INLabs authentication system."""
    
    def __init__(self):
        self.session = requests.Session()
        self.results: list[AuthTestResult] = []
        self.session_start_time: datetime | None = None
        
    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
    
    def _make_request(self, method: str, url: str, **kwargs) -> tuple[requests.Response, float]:
        """Make a request with timing."""
        start = time.time()
        response = self.session.request(method, url, **kwargs)
        elapsed_ms = (time.time() - start) * 1000
        return response, elapsed_ms
    
    def _record_result(self, name: str, response: requests.Response | None, 
                       elapsed_ms: float, notes: list[str] = None,
                       html_snippet: str = "") -> AuthTestResult:
        """Record test result."""
        # Extract cookies with details
        cookies_info = {}
        for cookie in self.session.cookies:
            cookies_info[cookie.name] = {
                "value": cookie.value[:20] + "..." if len(cookie.value) > 20 else cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "expires": cookie.expires,
                "secure": cookie.secure,
                "httpOnly": cookie.has_nonstandard_attr("HttpOnly") or "httponly" in str(cookie).lower(),
            }
        
        status_code = response.status_code if response else None
        headers = dict(response.headers) if response else {}
        success = response.status_code < 400 if response else True
        
        result = AuthTestResult(
            test_name=name,
            timestamp=self._now(),
            success=success,
            status_code=status_code,
            cookies=cookies_info,
            headers=headers,
            response_time_ms=elapsed_ms,
            notes=notes or [],
            html_snippet=html_snippet[:500] if html_snippet else ""
        )
        self.results.append(result)
        return result
    
    def test_1_login_page_analysis(self) -> AuthTestResult:
        """Test 1: Analyze login page for CSRF tokens and form structure."""
        print("\n[TEST 1] Analyzing login page...")
        
        response, elapsed_ms = self._make_request("GET", BASE_URL + "/")
        html = response.text
        
        notes = []
        
        # Check for CSRF tokens
        csrf_patterns = [
            'csrf', '_token', 'token', 'csrf_token', 
            'authenticity_token', '__RequestVerificationToken'
        ]
        found_csrf = []
        for pattern in csrf_patterns:
            if pattern.lower() in html.lower():
                found_csrf.append(pattern)
        
        if found_csrf:
            notes.append(f"Potential CSRF tokens found: {found_csrf}")
        else:
            notes.append("No CSRF tokens found in login form")
        
        # Check form fields - look for the login form specifically
        login_form_match = re.search(r'<form[^>]*action="logar\.php"[^>]*>(.*?)</form>', html, re.DOTALL | re.IGNORECASE)
        if login_form_match:
            login_form = login_form_match.group(1)
            notes.append("Login form found (action=logar.php)")
            
            if 'name="email"' in login_form:
                notes.append("✓ Email field detected")
            if 'name="password"' in login_form:
                notes.append("✓ Password field detected")
            if 'captcha' in login_form.lower():
                notes.append("WARNING: CAPTCHA detected in login form")
            
            # Check for hidden fields in login form
            hidden_fields = re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]*)"[^>]*>', login_form, re.IGNORECASE)
            if hidden_fields:
                notes.append(f"Hidden form fields: {hidden_fields}")
            else:
                notes.append("No hidden fields in login form")
        else:
            notes.append("ERROR: Login form not found!")
        
        # Check for JavaScript validation
        if '<script' in html.lower():
            notes.append("JavaScript detected on page (may have client-side validation)")
        
        # Look for all forms
        all_forms = re.findall(r'<form[^>]*action="([^"]*)"', html, re.IGNORECASE)
        notes.append(f"All forms on page: {all_forms}")
        
        return self._record_result(
            "Login Page Analysis",
            response,
            elapsed_ms,
            notes,
            html[:1000]
        )
    
    def test_2_authentication_flow(self) -> AuthTestResult:
        """Test 2: Perform actual authentication."""
        print("\n[TEST 2] Testing authentication flow...")
        
        # First get the main page to capture any cookies/session
        self.session.get(BASE_URL + "/")
        
        # Prepare login data - exactly matching the form
        login_data = {
            "email": CREDENTIALS["email"],
            "password": CREDENTIALS["password"],
        }
        
        response, elapsed_ms = self._make_request(
            "POST", 
            LOGIN_URL, 
            data=login_data,
            allow_redirects=True
        )
        
        notes = []
        
        # Check cookies after login
        cookie_names = [c.name for c in self.session.cookies]
        notes.append(f"Cookies after login: {cookie_names}")
        
        # Check for expected cookies
        expected_cookies = ['PHPSESSID', 'inlabs_session_cookie', 'TS016f630c']
        for cookie in expected_cookies:
            if cookie in cookie_names:
                notes.append(f"✓ Found expected cookie: {cookie}")
            else:
                notes.append(f"✗ Missing expected cookie: {cookie}")
        
        # Check redirect behavior
        if response.history:
            notes.append(f"Redirects: {[r.status_code for r in response.history]} → {response.status_code}")
            for i, r in enumerate(response.history):
                notes.append(f"  Redirect {i+1}: {r.url}")
        
        # Check if login was successful
        html_lower = response.text.lower()
        if "logout" in html_lower or "sair" in html_lower:
            notes.append("✓ Login appears successful (logout link found)")
            self.session_start_time = datetime.now(timezone.utc)
        elif "erro" in html_lower or "invalid" in html_lower or "incorreta" in html_lower:
            notes.append("✗ Login appears to have failed (error message)")
        elif "bem vindo" in html_lower or "bem-vindo" in html_lower:
            notes.append("✓ Login appears successful (welcome message)")
            self.session_start_time = datetime.now(timezone.utc)
        else:
            notes.append("? Login status unclear - check HTML snippet")
        
        return self._record_result(
            "Authentication Flow",
            response,
            elapsed_ms,
            notes,
            response.text[:800]
        )
    
    def test_3_session_persistence(self) -> AuthTestResult:
        """Test 3: Test if session persists across requests."""
        print("\n[TEST 3] Testing session persistence...")
        
        notes = []
        
        # Make multiple requests to the index page
        for i in range(3):
            response, elapsed_ms = self._make_request("GET", INDEX_URL)
            cookie_names = [c.name for c in self.session.cookies]
            notes.append(f"Request {i+1}: status={response.status_code}, cookies={cookie_names}")
            time.sleep(0.5)
        
        # Check if session is still valid (look for authenticated content)
        response, _ = self._make_request("GET", INDEX_URL)
        html_lower = response.text.lower()
        
        # Check for authenticated indicators
        if "logout" in html_lower or "sair" in html_lower:
            notes.append("✓ Session persisted - still authenticated")
        elif "login" in html_lower and "logar.php" in html_lower:
            notes.append("✗ Session not valid - redirected to login")
        else:
            notes.append("? Session status unclear")
        
        return self._record_result(
            "Session Persistence",
            response,
            0,
            notes
        )
    
    def test_4_cookie_properties(self) -> AuthTestResult:
        """Test 4: Analyze cookie properties."""
        print("\n[TEST 4] Analyzing cookie properties...")
        
        notes = []
        
        for cookie in self.session.cookies:
            notes.append(f"\n--- Cookie: {cookie.name} ---")
            notes.append(f"  Domain: {cookie.domain}")
            notes.append(f"  Path: {cookie.path}")
            notes.append(f"  Secure: {cookie.secure}")
            notes.append(f"  HttpOnly: {cookie.has_nonstandard_attr('HttpOnly') or 'httponly' in str(cookie).lower()}")
            notes.append(f"  Expires: {cookie.expires}")
            
            if cookie.expires:
                expires_dt = datetime.fromtimestamp(cookie.expires, tz=timezone.utc)
                notes.append(f"  Expires (human): {expires_dt.isoformat()}")
                
                if self.session_start_time:
                    session_duration = (expires_dt - self.session_start_time).total_seconds()
                    notes.append(f"  Session lifetime: ~{session_duration/60:.1f} minutes")
            else:
                notes.append("  Session cookie (no explicit expiration - browser session)")
        
        return self._record_result(
            "Cookie Properties",
            None,
            0,
            notes
        )
    
    def test_5_session_validity_duration(self) -> AuthTestResult:
        """Test 5: Measure how long a session stays valid."""
        print("\n[TEST 5] Measuring session validity (this may take a few minutes)...")
        
        notes = []
        check_interval = 30  # seconds
        max_checks = 10  # ~5 minutes max
        
        is_authenticated = True
        for i in range(max_checks):
            time.sleep(check_interval)
            
            response, elapsed_ms = self._make_request("GET", INDEX_URL)
            elapsed_since_start = (i + 1) * check_interval
            
            # Check if still authenticated
            html_lower = response.text.lower()
            is_authenticated = "logout" in html_lower or "sair" in html_lower
            
            notes.append(f"T+{elapsed_since_start}s: status={response.status_code}, authenticated={is_authenticated}")
            
            if not is_authenticated:
                notes.append(f"✗ Session expired or logged out after ~{elapsed_since_start} seconds")
                break
        else:
            notes.append(f"✓ Session still valid after {max_checks * check_interval} seconds")
        
        return self._record_result(
            "Session Validity Duration",
            response,
            0,
            notes
        )
    
    def test_6_logout_behavior(self) -> AuthTestResult:
        """Test 6: Test logout behavior."""
        print("\n[TEST 6] Testing logout behavior...")
        
        notes = []
        
        # Record cookies before logout
        cookies_before = [c.name for c in self.session.cookies]
        notes.append(f"Cookies before logout: {cookies_before}")
        
        try:
            response, elapsed_ms = self._make_request("GET", LOGOUT_URL)
            notes.append(f"Logout URL status: {response.status_code}")
        except Exception as e:
            notes.append(f"Logout URL error: {e}")
            elapsed_ms = 0
            response = None
        
        # Check cookies after logout attempt
        cookies_after = [c.name for c in self.session.cookies]
        notes.append(f"Cookies after logout: {cookies_after}")
        
        # Check if cookies were cleared
        cleared_cookies = set(cookies_before) - set(cookies_after)
        if cleared_cookies:
            notes.append(f"Cookies cleared: {cleared_cookies}")
        else:
            notes.append("No cookies were cleared (server-side session invalidation only)")
        
        # Try to access protected page after logout
        response2, _ = self._make_request("GET", BASE_URL + "/")
        html_lower = response2.text.lower()
        if "logar.php" in html_lower or "login" in html_lower:
            notes.append("✓ Redirected to login page after logout")
        
        return self._record_result(
            "Logout Behavior",
            response or response2,
            elapsed_ms if response else 0,
            notes,
            response2.text[:500] if response2 else ""
        )
    
    def test_7_rate_limiting(self) -> AuthTestResult:
        """Test 7: Check for rate limiting on login attempts."""
        print("\n[TEST 7] Testing rate limiting (5 rapid login attempts)...")
        
        notes = []
        
        # Create a fresh session
        self.session = requests.Session()
        
        for i in range(5):
            login_data = {
                "email": CREDENTIALS["email"],
                "password": "wrong_password",  # Intentionally wrong
            }
            
            start = time.time()
            response = self.session.post(LOGIN_URL, data=login_data)
            elapsed_ms = (time.time() - start) * 1000
            
            notes.append(f"Attempt {i+1}: status={response.status_code}, time={elapsed_ms:.1f}ms")
            
            # Check for rate limiting indicators
            if response.status_code == 429:
                notes.append("✗ Rate limited (HTTP 429)")
                break
            
            html_lower = response.text.lower()
            if "muitas tentativas" in html_lower or "too many" in html_lower:
                notes.append("✗ Rate limiting message detected")
                break
            if "aguarde" in html_lower or "wait" in html_lower:
                notes.append("✗ Rate limiting message detected")
                break
            if elapsed_ms > 2000:  # Significant delay
                notes.append(f"✗ Slow response detected ({elapsed_ms:.1f}ms) - possible throttling")
            
            time.sleep(0.5)
        else:
            notes.append("✓ No obvious rate limiting detected in 5 attempts")
        
        return self._record_result(
            "Rate Limiting Test",
            response,
            elapsed_ms,
            notes
        )
    
    def test_8_new_session_login(self) -> AuthTestResult:
        """Test 8: Login with fresh session to analyze initial cookie setup."""
        print("\n[TEST 8] Testing fresh session login...")
        
        # Create completely fresh session
        self.session = requests.Session()
        
        notes = []
        
        # Step 1: Get main page (no cookies initially)
        response1, elapsed1 = self._make_request("GET", BASE_URL + "/")
        initial_cookies = [c.name for c in self.session.cookies]
        notes.append(f"After GET /: cookies={initial_cookies}")
        
        # Step 2: Post credentials
        login_data = {
            "email": CREDENTIALS["email"],
            "password": CREDENTIALS["password"],
        }
        
        response2, elapsed2 = self._make_request(
            "POST",
            LOGIN_URL,
            data=login_data,
            allow_redirects=True
        )
        
        post_cookies = [c.name for c in self.session.cookies]
        notes.append(f"After POST /logar.php: cookies={post_cookies}")
        
        # Step 3: Follow redirect to index
        response3, elapsed3 = self._make_request("GET", INDEX_URL)
        final_cookies = [c.name for c in self.session.cookies]
        notes.append(f"After GET /index.php: cookies={final_cookies}")
        
        # Check which cookies are new
        new_cookies = set(final_cookies) - set(initial_cookies)
        if new_cookies:
            notes.append(f"New cookies after login: {new_cookies}")
        
        # Check for redirect
        if response2.history:
            notes.append(f"Login redirects to: {response2.url}")
        
        # Check authentication status
        html_lower = response3.text.lower()
        if "logout" in html_lower or "sair" in html_lower:
            notes.append("✓ Successfully authenticated")
        else:
            notes.append("? Authentication status unclear")
        
        return self._record_result(
            "Fresh Session Login",
            response3,
            elapsed1 + elapsed2 + elapsed3,
            notes
        )
    
    def test_9_security_headers(self) -> AuthTestResult:
        """Test 9: Analyze security headers."""
        print("\n[TEST 9] Analyzing security headers...")
        
        response, elapsed_ms = self._make_request("GET", BASE_URL + "/")
        
        notes = []
        headers = response.headers
        
        security_headers = {
            'Strict-Transport-Security': 'HSTS',
            'X-Frame-Options': 'Clickjacking protection',
            'X-Content-Type-Options': 'MIME sniffing protection',
            'X-XSS-Protection': 'XSS filter',
            'Content-Security-Policy': 'CSP',
            'Referrer-Policy': 'Referrer policy',
        }
        
        notes.append("Security Headers:")
        for header, description in security_headers.items():
            value = headers.get(header, 'NOT SET')
            status = "✓" if value != 'NOT SET' else "✗"
            notes.append(f"  {status} {header} ({description}): {value}")
        
        # Check cache headers
        notes.append("\nCache Headers:")
        cache_headers = ['Cache-Control', 'Expires', 'Pragma', 'ETag']
        for header in cache_headers:
            value = headers.get(header, 'NOT SET')
            notes.append(f"  {header}: {value}")
        
        # Check server info
        server = headers.get('Server', 'NOT DISCLOSED')
        notes.append(f"\nServer: {server}")
        
        return self._record_result(
            "Security Headers",
            response,
            elapsed_ms,
            notes
        )
    
    def generate_report(self) -> str:
        """Generate detailed report."""
        report = []
        report.append("=" * 80)
        report.append("INLABS AUTHENTICATION SYSTEM ANALYSIS REPORT")
        report.append("=" * 80)
        report.append(f"Generated: {self._now()}")
        report.append(f"Target URL: {BASE_URL}")
        report.append("")
        
        for i, result in enumerate(self.results, 1):
            report.append(f"\n{'='*60}")
            report.append(f"TEST {i}: {result.test_name}")
            report.append(f"{'='*60}")
            report.append(f"Timestamp: {result.timestamp}")
            report.append(f"Success: {result.success}")
            if result.status_code:
                report.append(f"Status Code: {result.status_code}")
            if result.response_time_ms:
                report.append(f"Response Time: {result.response_time_ms:.2f}ms")
            
            if result.notes:
                report.append("\nNotes:")
                for note in result.notes:
                    report.append(f"  • {note}")
            
            if result.cookies:
                report.append("\nCookies:")
                for name, details in result.cookies.items():
                    report.append(f"  {name}:")
                    for key, value in details.items():
                        report.append(f"    {key}: {value}")
            
            if result.html_snippet:
                report.append("\nHTML Snippet:")
                report.append(result.html_snippet[:400] + "...")
        
        report.append("\n" + "=" * 80)
        report.append("END OF REPORT")
        report.append("=" * 80)
        
        return "\n".join(report)


def main():
    """Run all authentication tests."""
    print("=" * 80)
    print("INLABS AUTHENTICATION SYSTEM ANALYSIS")
    print("=" * 80)
    
    analyzer = INLabsAuthAnalyzer()
    
    # Run tests
    analyzer.test_1_login_page_analysis()
    analyzer.test_2_authentication_flow()
    analyzer.test_3_session_persistence()
    analyzer.test_4_cookie_properties()
    analyzer.test_5_session_validity_duration()
    analyzer.test_6_logout_behavior()
    analyzer.test_7_rate_limiting()
    analyzer.test_8_new_session_login()
    analyzer.test_9_security_headers()
    
    # Generate and save report
    report = analyzer.generate_report()
    
    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    
    # Save report
    report_file = "/home/parallels/dev/gabi-kimi/inlabs_auth_report.txt"
    with open(report_file, 'w') as f:
        f.write(report)
    
    print(f"\nReport saved to: {report_file}")
    
    # Also print summary
    print("\n" + report)


if __name__ == "__main__":
    main()
