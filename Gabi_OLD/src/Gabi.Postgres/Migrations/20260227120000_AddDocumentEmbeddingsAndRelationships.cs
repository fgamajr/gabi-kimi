using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Gabi.Postgres.Migrations;

public partial class AddDocumentEmbeddingsAndRelationships : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        // Ensure pgvector extension is available
        migrationBuilder.Sql("CREATE EXTENSION IF NOT EXISTS \"vector\";");

        // Vector store: document chunk embeddings (384-dim via sentence-transformers)
        migrationBuilder.Sql("""
            CREATE TABLE document_embeddings (
                "Id"            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                "DocumentId"    UUID NOT NULL REFERENCES documents("Id") ON DELETE CASCADE,
                "SourceId"      VARCHAR(100) NOT NULL,
                "ChunkIndex"    INT NOT NULL,
                "ChunkText"     TEXT NOT NULL,
                "Embedding"     vector(384) NOT NULL,
                "ModelName"     VARCHAR(128) NOT NULL,
                "CreatedAt"     TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_doc_emb_chunk UNIQUE ("DocumentId", "ChunkIndex")
            );
            """);

        migrationBuilder.Sql("""CREATE INDEX CONCURRENTLY ix_doc_emb_document_id ON document_embeddings ("DocumentId");""");
        migrationBuilder.Sql("""CREATE INDEX CONCURRENTLY ix_doc_emb_source_id ON document_embeddings ("SourceId");""");

        // Knowledge graph store: document-to-document relationships
        migrationBuilder.Sql("""
            CREATE TABLE document_relationships (
                "Id"               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                "SourceDocumentId" UUID NOT NULL REFERENCES documents("Id") ON DELETE CASCADE,
                "TargetDocumentId" UUID NULL REFERENCES documents("Id") ON DELETE SET NULL,
                "TargetRef"        VARCHAR(512) NOT NULL,
                "RelationType"     VARCHAR(64) NOT NULL,
                "Confidence"       FLOAT NOT NULL DEFAULT 1.0,
                "ExtractedFrom"    VARCHAR(64) NOT NULL,
                "CreatedAt"        TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_doc_rel UNIQUE ("SourceDocumentId", "TargetRef", "RelationType")
            );
            """);

        migrationBuilder.Sql("""CREATE INDEX CONCURRENTLY ix_doc_rel_source ON document_relationships ("SourceDocumentId");""");
        migrationBuilder.Sql("""CREATE INDEX CONCURRENTLY ix_doc_rel_target ON document_relationships ("TargetDocumentId") WHERE "TargetDocumentId" IS NOT NULL;""");
        migrationBuilder.Sql("""CREATE INDEX CONCURRENTLY ix_doc_rel_type ON document_relationships ("RelationType");""");
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.Sql("DROP TABLE IF EXISTS document_relationships;");
        migrationBuilder.Sql("DROP TABLE IF EXISTS document_embeddings;");
    }
}
