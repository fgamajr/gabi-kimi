"""Testes unitários para o modelo ChangeDetectionCache.

Testa propriedades, métodos e comportamentos do cache de detecção.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from gabi.models.cache import ChangeDetectionCache


class TestChangeDetectionCacheCreation:
    """Testes para criação de ChangeDetectionCache."""
    
    def test_cache_creation_with_required_fields(self):
        """Verifica criação com campos obrigatórios."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
        )
        assert cache.source_id == "test_source"
        assert cache.url == "https://example.com/data.json"
    
    def test_cache_default_check_count_is_zero(self):
        """Verifica que check_count padrão é 0."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
        )
        assert cache.check_count == 0
    
    def test_cache_default_change_count_is_zero(self):
        """Verifica que change_count padrão é 0."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
        )
        assert cache.change_count == 0


class TestChangeDetectionCacheProperties:
    """Testes para propriedades de ChangeDetectionCache."""
    
    def test_has_change_detection_returns_true_with_etag(self):
        """Verifica que has_change_detection retorna True com ETag."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            etag='"abc123"',
        )
        assert cache.has_change_detection is True
    
    def test_has_change_detection_returns_true_with_last_modified(self):
        """Verifica que has_change_detection retorna True com Last-Modified."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            last_modified="Wed, 21 Oct 2024 07:28:00 GMT",
        )
        assert cache.has_change_detection is True
    
    def test_has_change_detection_returns_true_with_content_hash(self):
        """Verifica que has_change_detection retorna True com content_hash."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            content_hash="sha256abc123",
        )
        assert cache.has_change_detection is True
    
    def test_has_change_detection_returns_false_when_empty(self):
        """Verifica que has_change_detection retorna False quando vazio."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
        )
        assert cache.has_change_detection is False
    
    def test_is_fresh_returns_true_when_recently_checked(self):
        """Verifica que is_fresh retorna True quando verificado recentemente."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            last_checked_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        assert cache.is_fresh is True
    
    def test_is_fresh_returns_false_when_old_check(self):
        """Verifica que is_fresh retorna False quando verificação antiga."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            last_checked_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        assert cache.is_fresh is False
    
    def test_is_fresh_returns_false_when_never_checked(self):
        """Verifica que is_fresh retorna False quando nunca verificado."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            last_checked_at=None,
        )
        assert cache.is_fresh is False
    
    def test_change_rate_returns_zero_when_no_checks(self):
        """Verifica que change_rate retorna 0.0 quando sem verificações."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            check_count=0,
            change_count=0,
        )
        assert cache.change_rate == 0.0
    
    def test_change_rate_calculates_correctly(self):
        """Verifica que change_rate calcula corretamente."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            check_count=100,
            change_count=25,
        )
        assert cache.change_rate == 0.25
    
    def test_detection_method_returns_etag_when_present(self):
        """Verifica que detection_method retorna 'etag' quando presente."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            etag='"abc123"',
        )
        assert cache.detection_method == "etag"
    
    def test_detection_method_returns_last_modified_when_present(self):
        """Verifica que detection_method retorna 'last_modified' quando presente."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            last_modified="Wed, 21 Oct 2024 07:28:00 GMT",
        )
        assert cache.detection_method == "last_modified"
    
    def test_detection_method_returns_content_hash_when_present(self):
        """Verifica que detection_method retorna 'content_hash' quando presente."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            content_hash="sha256abc123",
        )
        assert cache.detection_method == "content_hash"
    
    def test_detection_method_returns_none_when_empty(self):
        """Verifica que detection_method retorna 'none' quando vazio."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
        )
        assert cache.detection_method == "none"


class TestChangeDetectionCacheMethods:
    """Testes para métodos de ChangeDetectionCache."""
    
    def test_record_check_increments_check_count(self):
        """Verifica que record_check incrementa check_count."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            check_count=5,
        )
        cache.record_check(changed=False)
        assert cache.check_count == 6
    
    def test_record_check_sets_last_checked_at(self):
        """Verifica que record_check define last_checked_at."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
        )
        cache.record_check(changed=False)
        assert cache.last_checked_at is not None
    
    def test_record_check_increments_change_count_when_changed(self):
        """Verifica que record_check incrementa change_count quando changed=True."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            check_count=5,
            change_count=2,
        )
        cache.record_check(changed=True)
        assert cache.check_count == 6
        assert cache.change_count == 3
        assert cache.last_changed_at is not None
    
    def test_update_etag_sets_etag(self):
        """Verifica que update_etag define etag."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
        )
        cache.update_etag('"new-etag-123"')
        assert cache.etag == '"new-etag-123"'
    
    def test_update_last_modified_sets_last_modified(self):
        """Verifica que update_last_modified define last_modified."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
        )
        cache.update_last_modified("Wed, 21 Oct 2024 07:28:00 GMT")
        assert cache.last_modified == "Wed, 21 Oct 2024 07:28:00 GMT"
    
    def test_update_content_hash_sets_hash_and_length(self):
        """Verifica que update_content_hash define content_hash e content_length."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
        )
        cache.update_content_hash("sha256xyz789", 1024)
        assert cache.content_hash == "sha256xyz789"
        assert cache.content_length == 1024
    
    def test_has_changed_from_compares_etag(self):
        """Verifica que has_changed_from compara ETag corretamente."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            etag='"abc123"',
        )
        assert cache.has_changed_from(etag='"xyz789"') is True
        assert cache.has_changed_from(etag='"abc123"') is False
    
    def test_has_changed_from_compares_last_modified(self):
        """Verifica que has_changed_from compara Last-Modified corretamente."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            last_modified="Wed, 21 Oct 2024 07:28:00 GMT",
        )
        assert cache.has_changed_from(last_modified="Wed, 21 Oct 2024 08:00:00 GMT") is True
        assert cache.has_changed_from(last_modified="Wed, 21 Oct 2024 07:28:00 GMT") is False
    
    def test_has_changed_from_compares_content_hash(self):
        """Verifica que has_changed_from compara content_hash corretamente."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
            content_hash="hash123",
        )
        assert cache.has_changed_from(content_hash="hash456") is True
        assert cache.has_changed_from(content_hash="hash123") is False
    
    def test_has_changed_from_returns_true_when_no_mechanism(self):
        """Verifica que has_changed_from retorna True quando sem mecanismo."""
        cache = ChangeDetectionCache(
            source_id="test_source",
            url="https://example.com/data.json",
        )
        assert cache.has_changed_from() is True


class TestChangeDetectionCacheConstraints:
    """Testes para constraints de ChangeDetectionCache."""
    
    def test_has_source_id_index(self):
        """Verifica que há índice por source_id."""
        table_args = ChangeDetectionCache.__table_args__
        assert any("idx_change_detection_source" in str(arg) for arg in table_args)
    
    def test_has_last_checked_at_index(self):
        """Verifica que há índice por last_checked_at."""
        table_args = ChangeDetectionCache.__table_args__
        assert any("idx_change_detection_checked" in str(arg) for arg in table_args)
    
    def test_has_unique_constraint_source_url(self):
        """Verifica que há constraint única para source_id + url."""
        table_args = ChangeDetectionCache.__table_args__
        assert any("idx_change_detection_url_source" in str(arg) for arg in table_args)
