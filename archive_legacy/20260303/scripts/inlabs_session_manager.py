#!/usr/bin/env python3
"""
INLabs Session Manager
Production-ready session management for INLabs/DOU access.
"""
from __future__ import annotations

import time
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib.parse import urljoin

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('inlabs_session')


@dataclass
class INLabsCredentials:
    """INLabs credentials container."""
    email: str
    password: str


@dataclass
class INLabsSession:
    """Session state container."""
    phpsessid: str
    inlabs_session_cookie: str
    ts016f630c: str
    created_at: datetime
    expires_at: datetime
    
    def is_valid(self) -> bool:
        """Check if session is still valid."""
        return datetime.now(timezone.utc) < self.expires_at
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'phpsessid': self.phpsessid,
            'inlabs_session_cookie': self.inlabs_session_cookie,
            'ts016f630c': self.ts016f630c,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'INLabsSession':
        """Create from dictionary."""
        return cls(
            phpsessid=data['phpsessid'],
            inlabs_session_cookie=data['inlabs_session_cookie'],
            ts016f630c=data['ts016f630c'],
            created_at=datetime.fromisoformat(data['created_at']),
            expires_at=datetime.fromisoformat(data['expires_at']),
        )


class INLabsSessionManager:
    """
    Manages INLabs authentication sessions.
    
    Features:
    - Automatic session creation and renewal
    - Session persistence to disk
    - Cookie refresh tracking
    - Session validity checking
    
    Usage:
        manager = INLabsSessionManager(credentials)
        session = manager.get_session()
        
        # Use with requests
        response = session.get('https://inlabs.in.gov.br/...')
    """
    
    BASE_URL = "https://inlabs.in.gov.br"
    LOGIN_URL = f"{BASE_URL}/logar.php"
    INDEX_URL = f"{BASE_URL}/index.php"
    LOGOUT_URL = f"{BASE_URL}/logout.php"
    
    # Session lifetime (based on analysis - ~30 minutes)
    SESSION_LIFETIME_MINUTES = 30
    
    # Renewal threshold (renew when 5 minutes remaining)
    RENEWAL_THRESHOLD_MINUTES = 5
    
    def __init__(
        self,
        credentials: INLabsCredentials,
        session_file: Optional[str] = None,
        auto_renew: bool = True
    ):
        """
        Initialize session manager.
        
        Args:
            credentials: INLabs login credentials
            session_file: Path to store/load session (optional)
            auto_renew: Automatically renew session when nearing expiration
        """
        self.credentials = credentials
        self.session_file = Path(session_file) if session_file else None
        self.auto_renew = auto_renew
        
        self._session: Optional[INLabsSession] = None
        self._requests_session: Optional[requests.Session] = None
        
        # Try to load existing session
        if self.session_file:
            self._load_session()
    
    def _create_requests_session(self) -> requests.Session:
        """Create configured requests session."""
        session = requests.Session()
        
        # Add retry strategy
        adapter = HTTPAdapter(
            max_retries=3,
            pool_connections=10,
            pool_maxsize=10
        )
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        
        # Set default headers
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        })
        
        return session
    
    def _load_session(self) -> bool:
        """Load session from disk."""
        if not self.session_file or not self.session_file.exists():
            return False
        
        try:
            data = json.loads(self.session_file.read_text())
            self._session = INLabsSession.from_dict(data)
            
            if self._session.is_valid():
                logger.info(f"Loaded valid session from {self.session_file}")
                return True
            else:
                logger.info("Loaded session has expired")
                self._session = None
                return False
                
        except Exception as e:
            logger.warning(f"Failed to load session: {e}")
            return False
    
    def _save_session(self) -> None:
        """Save session to disk."""
        if not self.session_file or not self._session:
            return
        
        try:
            self.session_file.write_text(json.dumps(self._session.to_dict(), indent=2))
            logger.info(f"Saved session to {self.session_file}")
        except Exception as e:
            logger.warning(f"Failed to save session: {e}")
    
    def authenticate(self) -> INLabsSession:
        """
        Authenticate with INLabs and create new session.
        
        Returns:
            New INLabsSession
            
        Raises:
            AuthenticationError: If login fails
        """
        logger.info("Authenticating with INLabs...")
        
        session = self._create_requests_session()
        
        # Step 1: Get initial cookies by visiting the main page
        logger.debug("Fetching main page...")
        response = session.get(self.BASE_URL + "/", timeout=30)
        response.raise_for_status()
        
        # Step 2: Submit login credentials
        logger.debug("Submitting credentials...")
        login_data = {
            "email": self.credentials.email,
            "password": self.credentials.password,
        }
        
        response = session.post(
            self.LOGIN_URL,
            data=login_data,
            allow_redirects=True,
            timeout=30
        )
        response.raise_for_status()
        
        # Step 3: Verify login success
        if "logout" not in response.text.lower() and "sair" not in response.text.lower():
            raise AuthenticationError("Login failed - no logout link found in response")
        
        # Step 4: Extract cookies
        cookies = {c.name: c.value for c in session.cookies}
        
        required_cookies = ['PHPSESSID', 'inlabs_session_cookie', 'TS016f630c']
        for cookie in required_cookies:
            if cookie not in cookies:
                raise AuthenticationError(f"Missing required cookie: {cookie}")
        
        # Calculate expiration (based on inlabs_session_cookie expiration or default)
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(minutes=self.SESSION_LIFETIME_MINUTES)
        
        # Try to get actual expiration from cookie
        for cookie in session.cookies:
            if cookie.name == 'inlabs_session_cookie' and cookie.expires:
                expires_at = datetime.fromtimestamp(cookie.expires, tz=timezone.utc)
                break
        
        self._session = INLabsSession(
            phpsessid=cookies['PHPSESSID'],
            inlabs_session_cookie=cookies['inlabs_session_cookie'],
            ts016f630c=cookies['TS016f630c'],
            created_at=created_at,
            expires_at=expires_at
        )
        
        self._requests_session = session
        self._save_session()
        
        logger.info(f"Authentication successful, session expires at {expires_at}")
        return self._session
    
    def get_session(self) -> requests.Session:
        """
        Get authenticated requests session.
        
        Automatically creates or renews session if needed.
        
        Returns:
            Authenticated requests.Session
        """
        # Check if we need to authenticate
        needs_auth = (
            self._session is None or
            not self._session.is_valid() or
            self._should_renew()
        )
        
        if needs_auth:
            self.authenticate()
        elif self._requests_session is None:
            # Restore session to requests session
            self._requests_session = self._create_requests_session()
            self._apply_session_cookies(self._requests_session)
        
        return self._requests_session
    
    def _should_renew(self) -> bool:
        """Check if session should be renewed."""
        if not self.auto_renew or not self._session:
            return False
        
        time_remaining = self._session.expires_at - datetime.now(timezone.utc)
        return time_remaining < timedelta(minutes=self.RENEWAL_THRESHOLD_MINUTES)
    
    def _apply_session_cookies(self, session: requests.Session) -> None:
        """Apply stored session cookies to requests session."""
        if not self._session:
            return
        
        session.cookies.set('PHPSESSID', self._session.phpsessid, domain='inlabs.in.gov.br')
        session.cookies.set('inlabs_session_cookie', self._session.inlabs_session_cookie, domain='inlabs.in.gov.br')
        session.cookies.set('TS016f630c', self._session.ts016f630c, domain='inlabs.in.gov.br')
    
    def logout(self) -> None:
        """Logout and clear session."""
        if self._requests_session:
            try:
                self._requests_session.get(self.LOGOUT_URL, timeout=10)
                logger.info("Logged out successfully")
            except Exception as e:
                logger.warning(f"Logout request failed: {e}")
        
        self._session = None
        self._requests_session = None
        
        if self.session_file and self.session_file.exists():
            self.session_file.unlink()
            logger.info("Session file removed")
    
    def get_session_info(self) -> Optional[dict]:
        """Get current session information."""
        if not self._session:
            return None
        
        return {
            'created_at': self._session.created_at.isoformat(),
            'expires_at': self._session.expires_at.isoformat(),
            'is_valid': self._session.is_valid(),
            'time_remaining_minutes': (
                (self._session.expires_at - datetime.now(timezone.utc)).total_seconds() / 60
            ) if self._session.is_valid() else 0,
        }


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass


# Example usage and testing
if __name__ == "__main__":
    import os
    
    # Load credentials from environment or use defaults
    email = os.getenv('INLABS_USER', 'fgamajr@gmail.com')
    password = os.getenv('INLABS_PWD', 'kqg8YDZ2eya3exq_wev')
    
    credentials = INLabsCredentials(email=email, password=password)
    
    # Create session manager
    manager = INLabsSessionManager(
        credentials=credentials,
        session_file='/tmp/inlabs_session.json',
        auto_renew=True
    )
    
    try:
        # Get authenticated session
        session = manager.get_session()
        
        # Print session info
        info = manager.get_session_info()
        print("Session Info:")
        print(json.dumps(info, indent=2))
        
        # Test with a request
        response = session.get('https://inlabs.in.gov.br/')
        print(f"\nTest request status: {response.status_code}")
        print(f"Authenticated: {'logout' in response.text.lower()}")
        
    except AuthenticationError as e:
        print(f"Authentication failed: {e}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Optional: logout when done
        # manager.logout()
        pass
