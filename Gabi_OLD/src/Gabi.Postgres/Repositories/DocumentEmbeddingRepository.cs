using System.Globalization;
using Dapper;
using Gabi.Contracts.Embed;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.Extensions.Logging;
using Npgsql;

namespace Gabi.Postgres.Repositories;

public class DocumentEmbeddingRepository : IDocumentEmbeddingRepository
{
    private readonly GabiDbContext _context;
    private readonly ILogger<DocumentEmbeddingRepository> _logger;

    public DocumentEmbeddingRepository(GabiDbContext context, ILogger<DocumentEmbeddingRepository> logger)
    {
        _context = context;
        _logger = logger;
    }

    public async Task<int> UpsertChunkEmbeddingsAsync(Guid documentId, string sourceId,
        IReadOnlyList<ChunkEmbedding> chunks, CancellationToken ct = default)
    {
        if (chunks.Count == 0) return 0;

        var conn = _context.Database.GetDbConnection();
        if (conn.State == System.Data.ConnectionState.Closed)
            await ((NpgsqlConnection)conn).OpenAsync(ct);

        var upserted = 0;
        foreach (var chunk in chunks)
        {
            ct.ThrowIfCancellationRequested();
            // Dapper doesn't map Pgvector.Vector; pass as string for ::vector cast
            var vectorStr = "[" + string.Join(",", chunk.Embedding.Select(f => f.ToString("R", CultureInfo.InvariantCulture))) + "]";
            var result = await conn.ExecuteAsync(
                """
                INSERT INTO document_embeddings ("DocumentId", "SourceId", "ChunkIndex", "ChunkText", "Embedding", "ModelName", "CreatedAt")
                VALUES (@DocumentId, @SourceId, @ChunkIndex, @ChunkText, @Embedding::vector, @ModelName, now())
                ON CONFLICT ("DocumentId", "ChunkIndex")
                DO UPDATE SET "ChunkText" = EXCLUDED."ChunkText",
                              "Embedding" = EXCLUDED."Embedding",
                              "ModelName" = EXCLUDED."ModelName",
                              "CreatedAt" = now()
                """,
                new
                {
                    DocumentId = documentId,
                    SourceId = sourceId,
                    chunk.ChunkIndex,
                    chunk.ChunkText,
                    Embedding = vectorStr,
                    chunk.ModelName
                });
            upserted += result;
        }

        _logger.LogDebug("Upserted {Count} embeddings for document {DocumentId}", upserted, documentId);
        return upserted;
    }

    public async Task<bool> HasEmbeddingsAsync(Guid documentId, CancellationToken ct = default)
    {
        var conn = _context.Database.GetDbConnection();
        if (conn.State == System.Data.ConnectionState.Closed)
            await ((NpgsqlConnection)conn).OpenAsync(ct);

        var count = await conn.ExecuteScalarAsync<int>(
            """SELECT COUNT(1) FROM document_embeddings WHERE "DocumentId" = @DocumentId""",
            new { DocumentId = documentId });
        return count > 0;
    }

    public async Task<IReadOnlyList<VectorSearchResult>> SearchSimilarAsync(
        float[] queryVector, int topK, string? sourceId, CancellationToken ct = default)
    {
        var conn = _context.Database.GetDbConnection();
        if (conn.State == System.Data.ConnectionState.Closed)
            await ((NpgsqlConnection)conn).OpenAsync(ct);

        // Dapper doesn't map Pgvector.Vector; pass as string for ::vector cast
        var vectorStr = "[" + string.Join(",", queryVector.Select(f => f.ToString("R", CultureInfo.InvariantCulture))) + "]";
        string sql;
        object param;

        if (!string.IsNullOrWhiteSpace(sourceId))
        {
            sql = """
                SELECT "DocumentId", "ChunkIndex", "ChunkText",
                       "Embedding" <=> @QueryVector::vector AS "Distance"
                FROM document_embeddings
                WHERE "SourceId" = @SourceId
                ORDER BY "Embedding" <=> @QueryVector::vector
                LIMIT @TopK
                """;
            param = new { QueryVector = vectorStr, SourceId = sourceId, TopK = topK };
        }
        else
        {
            sql = """
                SELECT "DocumentId", "ChunkIndex", "ChunkText",
                       "Embedding" <=> @QueryVector::vector AS "Distance"
                FROM document_embeddings
                ORDER BY "Embedding" <=> @QueryVector::vector
                LIMIT @TopK
                """;
            param = new { QueryVector = vectorStr, TopK = topK };
        }

        var rows = await conn.QueryAsync<VectorSearchRow>(sql, param);
        return rows.Select(r => new VectorSearchResult(r.DocumentId, r.ChunkIndex, r.ChunkText, (float)r.Distance)).ToList();
    }

    private class VectorSearchRow
    {
        public Guid DocumentId { get; set; }
        public int ChunkIndex { get; set; }
        public string ChunkText { get; set; } = string.Empty;
        public double Distance { get; set; }
    }
}
