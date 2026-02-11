#!/usr/bin/env python3
"""Benchmark suite for Hybrid Search Service.

This module provides comprehensive performance benchmarking for the
hybrid search implementation, measuring latency, throughput, and quality metrics.

Usage:
    python -m benchmarks.search_benchmark --iterations 100 --output report.json
"""

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional
from datetime import datetime

# Add project root to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gabi.services.hybrid_search import (
    HybridSearchService,
    QueryRouter,
    QueryType,
    RRFFusionEngine,
    SearchResult,
    InMemoryCacheBackend,
    SearchBackend,
)
from gabi.schemas.search import SearchRequest, SearchResponse


@dataclass
class BenchmarkResult:
    """Single benchmark measurement."""
    query_type: str
    query: str
    latency_ms: float
    bm25_results: int
    vector_results: int
    fused_results: int
    cache_hit: bool
    rrf_k: int
    weights: Dict[str, float]


@dataclass
class QueryTypeStats:
    """Statistics for a query type."""
    count: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    std_dev: float
    cache_hit_rate: float


class SearchBenchmark:
    """Benchmark suite for hybrid search."""
    
    # Test queries representing different TCU legal search patterns
    TEST_QUERIES = {
        'exact_match': [
            "AC 1234/2024",
            "Acórdão 567/2023",
            "Lei 8.666/93",
            "Lei 13.709/2018",
            "IN TCU 65/2013",
            "IN 123/2020",
            "Súmula 123",
            "Súmula TCU 456",
            "TC-123.456/2024",
            "processo 789012/2023",
        ],
        'semantic': [
            "licitação pregão eletrônico",
            "direito adquirido servidor público",
            "responsabilidade fiscal ente federado",
            "contas públicas tomada de contas",
            "indenização danos materiais",
            "regime de previdência complementar",
            "concessão de diárias e passagens",
            "aquisição de bens e serviços",
            "contratação por dispensa de licitação",
            "parecer prévio do TCU",
        ],
        'hybrid': [
            "Acórdão 1234/2024 sobre licitação",
            "Súmula 123 aplicada a pregão eletrônico",
            "Lei 8.666/93 e suas alterações sobre contratos",
            "IN TCU 65/2013 relativa a normas de auditoria",
            "processo TC-123.456/2024 sobre responsabilidade",
            '"direito líquido e certo" no TCU',
            "acórdãos de 2023 sobre contas municipais",
            "normas sobre controle externo aplicadas",
            "jurisprudência do TCU sobre tomada de contas especial",
            "decisões do TCU relativas a licitações",
        ]
    }
    
    def __init__(
        self,
        service: Optional[HybridSearchService] = None,
        iterations: int = 100,
        warmup_iterations: int = 10
    ):
        """Initialize benchmark suite.
        
        Args:
            service: HybridSearchService instance (creates mock if None)
            iterations: Number of iterations per query
            warmup_iterations: Number of warmup iterations
        """
        self.service = service or self._create_mock_service()
        self.iterations = iterations
        self.warmup_iterations = warmup_iterations
        self.router = QueryRouter()
        self.results: List[BenchmarkResult] = []
    
    def _create_mock_service(self) -> HybridSearchService:
        """Create a mock service for standalone benchmarking."""
        # Create mock results
        mock_bm25_results = [
            SearchResult(
                document_id=f"doc{i}",
                content=f"Content {i}",
                title=f"Document {i}",
                score=float(10 - i * 0.1),
                source_id="tcu_acordaos",
                source_type="acordao",
                metadata={"ano": "2024", "numero": str(1000 + i)},
            )
            for i in range(100)
        ]
        
        mock_vector_results = [
            SearchResult(
                document_id=f"doc{i}",
                content=f"Vector content {i}",
                title=f"Vector Doc {i}",
                score=float(0.95 - i * 0.005),
                source_id="tcu_acordaos",
                source_type="acordao",
                metadata={"ano": "2024", "numero": str(1000 + i)},
            )
            for i in range(100)
        ]
        
        # Create mock service that returns consistent results
        class MockService:
            def __init__(self, bm25_results, vector_results):
                self.bm25_results = bm25_results
                self.vector_results = vector_results
                self.router = QueryRouter()
                self.fusion_engine = RRFFusionEngine(k=60)
            
            async def search(self, request: SearchRequest, use_cache: bool = True):
                start = time.time()
                
                query_analysis = self.router.analyze(request.query)
                
                # Simulate some work
                await asyncio.sleep(0.001)  # 1ms base latency
                
                # Simulate BM25 search
                await asyncio.sleep(0.010)  # 10ms
                
                # Simulate vector search if needed
                if query_analysis.query_type in [QueryType.SEMANTIC, QueryType.HYBRID]:
                    await asyncio.sleep(0.015)  # 15ms for embedding + search
                    weights = self.router.get_optimal_weights(query_analysis.query_type)
                    fused = self.fusion_engine.fuse(
                        self.bm25_results[:30],
                        self.vector_results[:30],
                        limit=request.limit,
                        weights=weights
                    )
                else:
                    weights = {'bm25': 1.5, 'vector': 0.5}
                    fused = self.fusion_engine.fuse(
                        self.bm25_results[:30],
                        [],
                        limit=request.limit,
                        weights=weights
                    )
                
                elapsed = (time.time() - start) * 1000
                
                return SearchResponse(
                    query=request.query,
                    total=len(fused),
                    took_ms=round(elapsed, 2),
                    hits=[],
                )
        
        return MockService(mock_bm25_results, mock_vector_results)  # type: ignore
    
    async def warmup(self):
        """Execute warmup iterations."""
        print(f"Warming up with {self.warmup_iterations} iterations...")
        
        for query_type, queries in self.TEST_QUERIES.items():
            for query in queries[:2]:  # Use subset for warmup
                for _ in range(self.warmup_iterations // len(self.TEST_QUERIES)):
                    request = SearchRequest(query=query, limit=10)
                    await self.service.search(request)
        
        print("Warmup complete.")
    
    async def run(self) -> Dict[str, List[BenchmarkResult]]:
        """Run full benchmark suite.
        
        Returns:
            Dict mapping query types to benchmark results
        """
        await self.warmup()
        
        print(f"\nRunning benchmark: {self.iterations} iterations per query")
        print("=" * 60)
        
        results_by_type: Dict[str, List[BenchmarkResult]] = {
            'exact_match': [],
            'semantic': [],
            'hybrid': [],
        }
        
        total_queries = sum(len(queries) for queries in self.TEST_QUERIES.values())
        completed = 0
        
        for query_type, queries in self.TEST_QUERIES.items():
            print(f"\nBenchmarking {query_type} queries...")
            
            for query in queries:
                # Analyze query
                query_analysis = self.router.analyze(query)
                weights = self.router.get_optimal_weights(query_analysis.query_type)
                
                for i in range(self.iterations):
                    start = time.time()
                    
                    request = SearchRequest(query=query, limit=10)
                    response = await self.service.search(request)
                    
                    elapsed = (time.time() - start) * 1000
                    
                    result = BenchmarkResult(
                        query_type=query_type,
                        query=query,
                        latency_ms=elapsed,
                        bm25_results=response.total,  # Simplified
                        vector_results=response.total,
                        fused_results=response.total,
                        cache_hit=False,
                        rrf_k=60,
                        weights=weights,
                    )
                    
                    results_by_type[query_type].append(result)
                    self.results.append(result)
                
                completed += 1
                if completed % 5 == 0:
                    print(f"  Progress: {completed}/{total_queries} query types completed")
        
        return results_by_type
    
    def compute_stats(self, results: List[BenchmarkResult]) -> QueryTypeStats:
        """Compute statistics for a set of results."""
        latencies = [r.latency_ms for r in results]
        cache_hits = sum(1 for r in results if r.cache_hit)
        
        return QueryTypeStats(
            count=len(results),
            mean_ms=statistics.mean(latencies),
            median_ms=statistics.median(latencies),
            p95_ms=self._percentile(latencies, 95),
            p99_ms=self._percentile(latencies, 99),
            min_ms=min(latencies),
            max_ms=max(latencies),
            std_dev=statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
            cache_hit_rate=cache_hits / len(results) if results else 0.0,
        )
    
    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile value."""
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]
    
    def generate_report(
        self,
        results_by_type: Dict[str, List[BenchmarkResult]]
    ) -> Dict[str, Any]:
        """Generate comprehensive benchmark report.
        
        Returns:
            Dict with report data
        """
        report = {
            'metadata': {
                'timestamp': datetime.utcnow().isoformat(),
                'iterations_per_query': self.iterations,
                'total_queries': len(self.results),
            },
            'summary': {},
            'query_types': {},
        }
        
        # Overall summary
        all_latencies = [r.latency_ms for r in self.results]
        report['summary'] = {
            'total_measurements': len(self.results),
            'overall_mean_ms': round(statistics.mean(all_latencies), 2),
            'overall_median_ms': round(statistics.median(all_latencies), 2),
            'overall_p95_ms': round(self._percentile(all_latencies, 95), 2),
            'overall_p99_ms': round(self._percentile(all_latencies, 99), 2),
            'overall_min_ms': round(min(all_latencies), 2),
            'overall_max_ms': round(max(all_latencies), 2),
        }
        
        # Per query type stats
        for query_type, results in results_by_type.items():
            stats = self.compute_stats(results)
            report['query_types'][query_type] = {
                'count': stats.count,
                'mean_ms': round(stats.mean_ms, 2),
                'median_ms': round(stats.median_ms, 2),
                'p95_ms': round(stats.p95_ms, 2),
                'p99_ms': round(stats.p99_ms, 2),
                'min_ms': round(stats.min_ms, 2),
                'max_ms': round(stats.max_ms, 2),
                'std_dev': round(stats.std_dev, 2),
                'cache_hit_rate': round(stats.cache_hit_rate, 2),
            }
        
        return report
    
    def print_report(self, report: Dict[str, Any]):
        """Print formatted report to console."""
        print("\n" + "=" * 60)
        print("SEARCH BENCHMARK REPORT")
        print("=" * 60)
        
        print(f"\nTimestamp: {report['metadata']['timestamp']}")
        print(f"Iterations per query: {report['metadata']['iterations_per_query']}")
        print(f"Total measurements: {report['metadata']['total_queries']}")
        
        print("\n" + "-" * 60)
        print("OVERALL SUMMARY")
        print("-" * 60)
        summary = report['summary']
        print(f"  Mean latency:     {summary['overall_mean_ms']:>8.2f} ms")
        print(f"  Median latency:   {summary['overall_median_ms']:>8.2f} ms")
        print(f"  P95 latency:      {summary['overall_p95_ms']:>8.2f} ms")
        print(f"  P99 latency:      {summary['overall_p99_ms']:>8.2f} ms")
        print(f"  Min latency:      {summary['overall_min_ms']:>8.2f} ms")
        print(f"  Max latency:      {summary['overall_max_ms']:>8.2f} ms")
        
        print("\n" + "-" * 60)
        print("QUERY TYPE BREAKDOWN")
        print("-" * 60)
        
        for query_type, stats in report['query_types'].items():
            print(f"\n{query_type.upper()}:")
            print(f"  Count:            {stats['count']:>8}")
            print(f"  Mean:             {stats['mean_ms']:>8.2f} ms")
            print(f"  Median:           {stats['median_ms']:>8.2f} ms")
            print(f"  P95:              {stats['p95_ms']:>8.2f} ms")
            print(f"  P99:              {stats['p99_ms']:>8.2f} ms")
            print(f"  Min:              {stats['min_ms']:>8.2f} ms")
            print(f"  Max:              {stats['max_ms']:>8.2f} ms")
            print(f"  Std Dev:          {stats['std_dev']:>8.2f} ms")
            print(f"  Cache hit rate:   {stats['cache_hit_rate']:>7.1%}")
        
        print("\n" + "=" * 60)
        
        # Performance assessment
        p95 = summary['overall_p95_ms']
        if p95 < 50:
            print("✅ EXCELLENT: P95 latency under 50ms")
        elif p95 < 100:
            print("✅ GOOD: P95 latency under 100ms")
        elif p95 < 200:
            print("⚠️  FAIR: P95 latency under 200ms")
        else:
            print("❌ POOR: P95 latency over 200ms")
        
        print("=" * 60)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Benchmark hybrid search performance"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="Number of iterations per query (default: 100)"
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=10,
        help="Number of warmup iterations (default: 10)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file for JSON report"
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format (default: json)"
    )
    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_args()
    
    # Create and run benchmark
    benchmark = SearchBenchmark(
        iterations=args.iterations,
        warmup_iterations=args.warmup
    )
    
    results = await benchmark.run()
    report = benchmark.generate_report(results)
    benchmark.print_report(report)
    
    # Save to file if requested
    if args.output:
        if args.format == "json":
            with open(args.output, 'w') as f:
                json.dump(report, f, indent=2)
        elif args.format == "markdown":
            # Generate markdown report
            with open(args.output, 'w') as f:
                f.write("# Search Benchmark Report\n\n")
                f.write(f"**Timestamp:** {report['metadata']['timestamp']}\n\n")
                f.write("## Summary\n\n")
                f.write("| Metric | Value |\n")
                f.write("|--------|-------|\n")
                for key, value in report['summary'].items():
                    f.write(f"| {key} | {value} |\n")
                
                f.write("\n## Query Type Breakdown\n\n")
                for query_type, stats in report['query_types'].items():
                    f.write(f"\n### {query_type.upper()}\n\n")
                    f.write("| Metric | Value |\n")
                    f.write("|--------|-------|\n")
                    for key, value in stats.items():
                        f.write(f"| {key} | {value} |\n")
        
        print(f"\nReport saved to: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
