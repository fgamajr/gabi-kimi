using Dapper;
using Gabi.Contracts.Graph;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.Extensions.Logging;
using Npgsql;

namespace Gabi.Postgres.Repositories;

public class DocumentRelationshipRepository : IDocumentRelationshipRepository
{
    private readonly GabiDbContext _context;
    private readonly ILogger<DocumentRelationshipRepository> _logger;

    public DocumentRelationshipRepository(GabiDbContext context, ILogger<DocumentRelationshipRepository> logger)
    {
        _context = context;
        _logger = logger;
    }

    public async Task<int> UpsertRelationshipsAsync(Guid sourceDocId,
        IReadOnlyList<DocumentRelation> relations, CancellationToken ct = default)
    {
        if (relations.Count == 0) return 0;

        var conn = _context.Database.GetDbConnection();
        if (conn.State == System.Data.ConnectionState.Closed)
            await ((NpgsqlConnection)conn).OpenAsync(ct);

        var upserted = 0;
        foreach (var rel in relations)
        {
            ct.ThrowIfCancellationRequested();
            var result = await conn.ExecuteAsync(
                """
                INSERT INTO document_relationships ("SourceDocumentId", "TargetDocumentId", "TargetRef", "RelationType", "Confidence", "ExtractedFrom", "CreatedAt")
                VALUES (@SourceDocumentId, @TargetDocumentId, @TargetRef, @RelationType, @Confidence, @ExtractedFrom, now())
                ON CONFLICT ("SourceDocumentId", "TargetRef", "RelationType")
                DO UPDATE SET "Confidence" = EXCLUDED."Confidence",
                              "TargetDocumentId" = EXCLUDED."TargetDocumentId",
                              "CreatedAt" = now()
                """,
                new
                {
                    SourceDocumentId = sourceDocId,
                    rel.TargetDocumentId,
                    rel.TargetRef,
                    rel.RelationType,
                    rel.Confidence,
                    rel.ExtractedFrom
                });
            upserted += result;
        }

        _logger.LogDebug("Upserted {Count} relationships for document {DocumentId}", upserted, sourceDocId);
        return upserted;
    }

    public async Task<IReadOnlyList<DocumentRelation>> GetRelationshipsAsync(
        Guid documentId, CancellationToken ct = default)
    {
        var conn = _context.Database.GetDbConnection();
        if (conn.State == System.Data.ConnectionState.Closed)
            await ((NpgsqlConnection)conn).OpenAsync(ct);

        var rows = await conn.QueryAsync<RelationRow>(
            """
            SELECT "TargetRef", "RelationType", "Confidence", "ExtractedFrom", "TargetDocumentId"
            FROM document_relationships
            WHERE "SourceDocumentId" = @DocumentId
            ORDER BY "CreatedAt"
            """,
            new { DocumentId = documentId });

        return rows.Select(r => new DocumentRelation(
            r.TargetRef, r.RelationType, r.Confidence, r.ExtractedFrom, r.TargetDocumentId)).ToList();
    }

    public async Task<IReadOnlyList<GraphSearchResult>> SearchByRefAsync(
        string refPattern, int topK, CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(refPattern)) return Array.Empty<GraphSearchResult>();

        var conn = _context.Database.GetDbConnection();
        if (conn.State == System.Data.ConnectionState.Closed)
            await ((NpgsqlConnection)conn).OpenAsync(ct);

        var rows = await conn.QueryAsync<GraphRow>(
            """
            SELECT "SourceDocumentId", "TargetDocumentId", "TargetRef", "RelationType"
            FROM document_relationships
            WHERE "TargetRef" ILIKE @Pattern
            ORDER BY "Confidence" DESC, "CreatedAt" DESC
            LIMIT @TopK
            """,
            new { Pattern = $"%{refPattern}%", TopK = topK });

        return rows.Select(r => new GraphSearchResult(
            r.SourceDocumentId, r.TargetDocumentId, r.TargetRef, r.RelationType)).ToList();
    }

    public async Task<int> ReconcileTargetRefsAsync(CancellationToken ct = default)
    {
        var conn = _context.Database.GetDbConnection();
        if (conn.State == System.Data.ConnectionState.Closed)
            await ((NpgsqlConnection)conn).OpenAsync(ct);

        var result = await conn.ExecuteAsync(
            """
            UPDATE document_relationships dr
            SET "TargetDocumentId" = d."Id"
            FROM documents d
            WHERE dr."TargetDocumentId" IS NULL
              AND d."ExternalId" = dr."TargetRef"
              AND d."RemovedFromSourceAt" IS NULL
            """);

        if (result > 0)
            _logger.LogInformation("Reconciled {Count} document relationship target refs", result);
        return result;
    }

    private class RelationRow
    {
        public string TargetRef { get; set; } = string.Empty;
        public string RelationType { get; set; } = string.Empty;
        public float Confidence { get; set; }
        public string ExtractedFrom { get; set; } = string.Empty;
        public Guid? TargetDocumentId { get; set; }
    }

    private class GraphRow
    {
        public Guid SourceDocumentId { get; set; }
        public Guid? TargetDocumentId { get; set; }
        public string TargetRef { get; set; } = string.Empty;
        public string RelationType { get; set; } = string.Empty;
    }
}
