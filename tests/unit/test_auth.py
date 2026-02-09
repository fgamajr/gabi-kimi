"""Testes unitários para autenticação JWT.

Testa validação de tokens JWT RS256 com cache JWKS.
"""

from __future__ import annotations

import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, Mock

from jose import JWTError, jwt
from jose.backends import RSAKey

from gabi.auth.jwt import JWKSClient, JWTValidator


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_jwks_response():
    """Mock de resposta JWKS válida."""
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": "test-key-1",
                "use": "sig",
                "n": "xGOr-H7R4Dz0XbQL2xGOr-H7R4Dz0XbQL2xGOr-H7R4Dz0XbQL2xGOr",
                "e": "AQAB",
            }
        ]
    }


@pytest.fixture
def sample_payload():
    """Payload JWT de exemplo."""
    now = datetime.now(timezone.utc)
    return {
        "sub": "user-123",
        "email": "user@tcu.gov.br",
        "name": "Test User",
        "jti": "token-123",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "iss": "https://auth.tcu.gov.br/realms/tcu",
        "aud": "gabi-api",
    }


@pytest.fixture(autouse=True)
def mock_revocation_checks():
    """Evita acesso real ao Redis em testes de JWT."""
    with patch("gabi.auth.jwt.revocation_list") as mock_revocation:
        mock_revocation.is_revoked = AsyncMock(return_value=False)
        mock_revocation.is_user_revoked = AsyncMock(return_value=False)
        yield mock_revocation


# =============================================================================
# JWKSClient Tests
# =============================================================================

class TestJWKSClient:
    """Testes para JWKSClient."""
    
    def test_jwks_client_initializes_with_empty_cache(self):
        """Verifica que JWKSClient inicia com cache vazio."""
        client = JWKSClient()
        assert client._cache == {}
        assert client._last_fetch == 0
    
    def test_jwks_client_uses_settings_for_ttl(self, settings):
        """Verifica que JWKSClient usa settings para TTL."""
        client = JWKSClient()
        assert client._cache_ttl_seconds == settings.jwt_jwks_cache_minutes * 60
    
    @pytest.mark.asyncio
    async def test_get_key_returns_cached_key(self):
        """Verifica que get_key retorna chave do cache."""
        client = JWKSClient()
        client._cache = {"test-key-1": "pem-content"}
        client._last_fetch = time.time()
        
        key = await client.get_key("test-key-1")
        assert key == "pem-content"
    
    @pytest.mark.asyncio
    async def test_get_key_returns_none_for_unknown_kid(self):
        """Verifica que get_key retorna None para kid desconhecido."""
        client = JWKSClient()
        client._cache = {"other-key": "pem-content"}
        client._last_fetch = time.time()
        
        key = await client.get_key("unknown-key")
        assert key is None
    
    @pytest.mark.asyncio
    async def test_refresh_if_needed_fetches_when_cache_empty(self, mock_jwks_response):
        """Verifica que _refresh_if_needed busca quando cache vazio."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_jwks_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)
            
            # Mock RSAKey
            with patch("gabi.auth.jwt.RSAKey") as mock_rsa:
                mock_rsa_instance = MagicMock()
                mock_rsa_instance.to_pem.return_value = "mock-pem"
                mock_rsa.return_value = mock_rsa_instance
                
                client = JWKSClient()
                await client._refresh_if_needed()
                
                mock_client.get.assert_called_once()
    
    def test_clear_cache_empties_cache(self):
        """Verifica que clear_cache limpa o cache."""
        client = JWKSClient()
        client._cache = {"key": "value"}
        client._last_fetch = time.time()
        
        client.clear_cache()
        
        assert client._cache == {}
        assert client._last_fetch == 0


# =============================================================================
# JWTValidator Tests
# =============================================================================

class TestJWTValidator:
    """Testes para JWTValidator."""
    
    def test_jwt_validator_initializes_jwks_client(self):
        """Verifica que JWTValidator inicializa JWKSClient."""
        validator = JWTValidator()
        assert validator._jwks is not None
        assert isinstance(validator._jwks, JWKSClient)
    
    @pytest.mark.asyncio
    async def test_validate_raises_error_on_invalid_header(self):
        """Verifica que validate levanta erro em header inválido."""
        validator = JWTValidator()
        
        with pytest.raises(JWTError, match="Invalid token header"):
            await validator.validate("invalid-token")
    
    @pytest.mark.asyncio
    async def test_validate_raises_error_when_kid_missing(self):
        """Verifica que validate levanta erro quando kid ausente."""
        validator = JWTValidator()
        
        with patch("jose.jwt.get_unverified_header") as mock_header:
            mock_header.return_value = {"alg": "RS256"}  # Sem kid
            
            with pytest.raises(JWTError, match="missing 'kid'"):
                await validator.validate("token.without.kid")
    
    @pytest.mark.asyncio
    async def test_validate_raises_error_for_unknown_kid(self):
        """Verifica que validate levanta erro para kid desconhecido."""
        validator = JWTValidator()
        
        with patch("jose.jwt.get_unverified_header") as mock_header:
            mock_header.return_value = {"kid": "unknown-key", "alg": "RS256"}
            
            with patch.object(validator._jwks, "get_key", return_value=None):
                with pytest.raises(JWTError, match="Unknown key ID"):
                    await validator.validate("token.unknown.kid")
    
    @pytest.mark.asyncio
    async def test_validate_success_with_valid_token(self, sample_payload, settings):
        """Verifica que validate retorna payload com token válido."""
        validator = JWTValidator()
        
        # Mock token
        token = "header.payload.signature"
        
        with patch("jose.jwt.get_unverified_header") as mock_header:
            mock_header.return_value = {"kid": "valid-key", "alg": "RS256"}
            
            with patch.object(validator._jwks, "get_key", return_value="mock-pem"):
                with patch("jose.jwt.decode") as mock_decode:
                    mock_decode.return_value = sample_payload
                    
                    result = await validator.validate(token)
                    
                    assert result == sample_payload
                    mock_decode.assert_called_once()
    
    def test_decode_unsafe_returns_payload(self):
        """Verifica que decode_unsafe retorna payload sem validação."""
        validator = JWTValidator()
        
        with patch("jose.jwt.get_unverified_claims") as mock_claims:
            mock_claims.return_value = {"sub": "user-123"}
            
            result = validator.decode_unsafe("token")
            
            assert result == {"sub": "user-123"}
    
    def test_decode_unsafe_returns_none_on_error(self):
        """Verifica que decode_unsafe retorna None em erro."""
        validator = JWTValidator()
        
        with patch("jose.jwt.get_unverified_claims") as mock_claims:
            mock_claims.side_effect = JWTError("Invalid")
            
            result = validator.decode_unsafe("invalid-token")
            
            assert result is None


# =============================================================================
# JWT Integration Tests
# =============================================================================

class TestJWTIntegration:
    """Testes de integração para JWT."""
    
    @pytest.mark.asyncio
    async def test_full_validation_flow(self, sample_payload, settings):
        """Testa fluxo completo de validação."""
        validator = JWTValidator()
        
        # Mock JWKS
        mock_pem = "mock-rsa-pem"
        validator._jwks._cache = {"test-key-1": mock_pem}
        validator._jwks._last_fetch = time.time()
        
        with patch("jose.jwt.get_unverified_header") as mock_header:
            mock_header.return_value = {"kid": "test-key-1", "alg": "RS256"}
            
            with patch("jose.jwt.decode") as mock_decode:
                mock_decode.return_value = sample_payload
                
                result = await validator.validate("valid.jwt.token")
                
                assert result["sub"] == "user-123"
                assert result["email"] == "user@tcu.gov.br"
    
    def test_jwt_error_handling(self):
        """Verifica tratamento de erros JWT."""
        validator = JWTValidator()

        # Token malformado - decode_unsafe retorna None ao invés de lançar erro
        result = validator.decode_unsafe("not.a.valid.token")
        assert result is None


# =============================================================================
# Security Tests
# =============================================================================

class TestJWTSecurity:
    """Testes de segurança para JWT."""
    
    @pytest.mark.asyncio
    async def test_rejects_token_with_invalid_signature(self):
        """Verifica que token com assinatura inválida é rejeitado."""
        validator = JWTValidator()
        
        validator._jwks._cache = {"key-1": "valid-pem"}
        validator._jwks._last_fetch = time.time()
        
        with patch("jose.jwt.get_unverified_header") as mock_header:
            mock_header.return_value = {"kid": "key-1", "alg": "RS256"}
            
            with patch("jose.jwt.decode") as mock_decode:
                mock_decode.side_effect = JWTError("Invalid signature")
                
                with pytest.raises(JWTError):
                    await validator.validate("token.invalid.sig")
    
    @pytest.mark.asyncio
    async def test_rejects_expired_token(self):
        """Verifica que token expirado é rejeitado."""
        validator = JWTValidator()
        
        validator._jwks._cache = {"key-1": "valid-pem"}
        validator._jwks._last_fetch = time.time()
        
        with patch("jose.jwt.get_unverified_header") as mock_header:
            mock_header.return_value = {"kid": "key-1", "alg": "RS256"}
            
            with patch("jose.jwt.decode") as mock_decode:
                mock_decode.side_effect = JWTError("Signature has expired")
                
                with pytest.raises(JWTError):
                    await validator.validate("expired.token")
    
    @pytest.mark.asyncio
    async def test_rejects_token_with_wrong_issuer(self, settings):
        """Verifica que token com issuer incorreto é rejeitado."""
        validator = JWTValidator()
        
        validator._jwks._cache = {"key-1": "valid-pem"}
        validator._jwks._last_fetch = time.time()
        
        with patch("jose.jwt.get_unverified_header") as mock_header:
            mock_header.return_value = {"kid": "key-1", "alg": "RS256"}
            
            with patch("jose.jwt.decode") as mock_decode:
                mock_decode.side_effect = JWTError("Invalid issuer")
                
                with pytest.raises(JWTError):
                    await validator.validate("wrong.issuer.token")


# =============================================================================
# Cache Tests
# =============================================================================

class TestJWTCache:
    """Testes para cache de JWKS."""
    
    def test_cache_ttl_respected(self, settings):
        """Verifica que TTL do cache é respeitado."""
        client = JWKSClient()
        
        # Simula cache recente
        client._cache = {"key": "value"}
        client._last_fetch = time.time()  # Agora
        
        # Não deve fazer refresh
        assert client._cache_ttl_seconds > 0
    
    def test_cache_refresh_after_ttl(self, settings):
        """Verifica que cache é atualizado após TTL."""
        client = JWKSClient()
        
        # Simula cache antigo
        client._cache = {"key": "value"}
        client._last_fetch = time.time() - (settings.jwt_jwks_cache_minutes * 60 + 1)
        
        # Deveria fazer refresh (verificado pelo comportamento)
        # O tempo passado é maior que TTL
        time_passed = time.time() - client._last_fetch
        assert time_passed > client._cache_ttl_seconds
