using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace Gabi.Postgres.Migrations
{
    /// <inheritdoc />
    public partial class AddPhase0DiscoverySchema : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_documents_DocumentId",
                table: "documents");

            migrationBuilder.DropIndex(
                name: "IX_documents_Fingerprint",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "Fingerprint",
                table: "documents");

            migrationBuilder.RenameColumn(
                name: "ContentPreview",
                table: "documents",
                newName: "UpdatedBy");

            // Postgres: drop identity then change bigint -> uuid (USING required; gen_random_uuid() for empty table or existing rows)
            migrationBuilder.Sql(@"ALTER TABLE ingest_jobs ALTER COLUMN ""Id"" DROP IDENTITY IF EXISTS;");
            migrationBuilder.Sql(@"ALTER TABLE ingest_jobs ALTER COLUMN ""Id"" SET DATA TYPE uuid USING gen_random_uuid();");

            migrationBuilder.AlterColumn<string>(
                name: "Title",
                table: "documents",
                type: "text",
                nullable: true,
                oldClrType: typeof(string),
                oldType: "character varying(1000)",
                oldMaxLength: 1000);

            migrationBuilder.AlterColumn<string>(
                name: "Status",
                table: "documents",
                type: "character varying(20)",
                maxLength: 20,
                nullable: false,
                oldClrType: typeof(int),
                oldType: "integer",
                oldMaxLength: 20);

            migrationBuilder.AlterColumn<string>(
                name: "DocumentId",
                table: "documents",
                type: "character varying(255)",
                maxLength: 255,
                nullable: true,
                oldClrType: typeof(string),
                oldType: "character varying(255)",
                oldMaxLength: 255);

            migrationBuilder.AlterColumn<string>(
                name: "ContentHash",
                table: "documents",
                type: "character varying(64)",
                maxLength: 64,
                nullable: true,
                oldClrType: typeof(string),
                oldType: "text");

            migrationBuilder.AddColumn<string>(
                name: "Content",
                table: "documents",
                type: "text",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "ContentUrl",
                table: "documents",
                type: "character varying(2048)",
                maxLength: 2048,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "CreatedBy",
                table: "documents",
                type: "text",
                nullable: false,
                defaultValue: "");

            migrationBuilder.AddColumn<string>(
                name: "ElasticsearchId",
                table: "documents",
                type: "character varying(255)",
                maxLength: 255,
                nullable: true);

            migrationBuilder.AddColumn<Guid>(
                name: "EmbeddingId",
                table: "documents",
                type: "uuid",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "ExternalId",
                table: "documents",
                type: "character varying(255)",
                maxLength: 255,
                nullable: true);

            migrationBuilder.AddColumn<long>(
                name: "LinkId",
                table: "documents",
                type: "bigint",
                nullable: false,
                defaultValue: 0L);

            migrationBuilder.AddColumn<string>(
                name: "Metadata",
                table: "documents",
                type: "jsonb",
                nullable: false,
                defaultValue: "");

            migrationBuilder.AddColumn<DateTime>(
                name: "ProcessingCompletedAt",
                table: "documents",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "ProcessingStage",
                table: "documents",
                type: "character varying(50)",
                maxLength: 50,
                nullable: true);

            migrationBuilder.AddColumn<DateTime>(
                name: "ProcessingStartedAt",
                table: "documents",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.AddColumn<DateTime>(
                name: "RemovedFromSourceAt",
                table: "documents",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "RemovedReason",
                table: "documents",
                type: "character varying(100)",
                maxLength: 100,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "SourceContentHash",
                table: "documents",
                type: "character varying(64)",
                maxLength: 64,
                nullable: true);

            migrationBuilder.AddColumn<uint>(
                name: "xmin",
                table: "documents",
                type: "xid",
                rowVersion: true,
                nullable: false,
                defaultValue: 0u);

            migrationBuilder.AddColumn<int>(
                name: "DocumentCount",
                table: "discovered_links",
                type: "integer",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "MetadataHash",
                table: "discovered_links",
                type: "character varying(64)",
                maxLength: 64,
                nullable: true);

            migrationBuilder.AddColumn<long>(
                name: "TotalSizeBytes",
                table: "discovered_links",
                type: "bigint",
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "IX_Documents_SourceId_ExternalId_Active",
                table: "documents",
                columns: new[] { "SourceId", "ExternalId" },
                unique: true,
                filter: "\"RemovedFromSourceAt\" IS NULL");

            migrationBuilder.CreateIndex(
                name: "IX_documents_ContentHash",
                table: "documents",
                column: "ContentHash");

            migrationBuilder.CreateIndex(
                name: "IX_documents_CreatedAt",
                table: "documents",
                column: "CreatedAt");

            migrationBuilder.CreateIndex(
                name: "IX_documents_DocumentId",
                table: "documents",
                column: "DocumentId");

            migrationBuilder.CreateIndex(
                name: "IX_documents_ExternalId",
                table: "documents",
                column: "ExternalId");

            migrationBuilder.CreateIndex(
                name: "IX_documents_LinkId",
                table: "documents",
                column: "LinkId");

            migrationBuilder.CreateIndex(
                name: "IX_documents_RemovedFromSourceAt",
                table: "documents",
                column: "RemovedFromSourceAt");

            migrationBuilder.CreateIndex(
                name: "IX_documents_Status",
                table: "documents",
                column: "Status");

            migrationBuilder.AddForeignKey(
                name: "FK_documents_discovered_links_LinkId",
                table: "documents",
                column: "LinkId",
                principalTable: "discovered_links",
                principalColumn: "Id",
                onDelete: ReferentialAction.Cascade);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropForeignKey(
                name: "FK_documents_discovered_links_LinkId",
                table: "documents");

            migrationBuilder.DropIndex(
                name: "IX_Documents_SourceId_ExternalId_Active",
                table: "documents");

            migrationBuilder.DropIndex(
                name: "IX_documents_ContentHash",
                table: "documents");

            migrationBuilder.DropIndex(
                name: "IX_documents_CreatedAt",
                table: "documents");

            migrationBuilder.DropIndex(
                name: "IX_documents_DocumentId",
                table: "documents");

            migrationBuilder.DropIndex(
                name: "IX_documents_ExternalId",
                table: "documents");

            migrationBuilder.DropIndex(
                name: "IX_documents_LinkId",
                table: "documents");

            migrationBuilder.DropIndex(
                name: "IX_documents_RemovedFromSourceAt",
                table: "documents");

            migrationBuilder.DropIndex(
                name: "IX_documents_Status",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "Content",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "ContentUrl",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "CreatedBy",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "ElasticsearchId",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "EmbeddingId",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "ExternalId",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "LinkId",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "Metadata",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "ProcessingCompletedAt",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "ProcessingStage",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "ProcessingStartedAt",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "RemovedFromSourceAt",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "RemovedReason",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "SourceContentHash",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "xmin",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "DocumentCount",
                table: "discovered_links");

            migrationBuilder.DropColumn(
                name: "MetadataHash",
                table: "discovered_links");

            migrationBuilder.DropColumn(
                name: "TotalSizeBytes",
                table: "discovered_links");

            migrationBuilder.RenameColumn(
                name: "UpdatedBy",
                table: "documents",
                newName: "ContentPreview");

            migrationBuilder.AlterColumn<long>(
                name: "Id",
                table: "ingest_jobs",
                type: "bigint",
                nullable: false,
                oldClrType: typeof(Guid),
                oldType: "uuid")
                .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn);

            migrationBuilder.AlterColumn<string>(
                name: "Title",
                table: "documents",
                type: "character varying(1000)",
                maxLength: 1000,
                nullable: false,
                defaultValue: "",
                oldClrType: typeof(string),
                oldType: "text",
                oldNullable: true);

            migrationBuilder.AlterColumn<int>(
                name: "Status",
                table: "documents",
                type: "integer",
                maxLength: 20,
                nullable: false,
                oldClrType: typeof(string),
                oldType: "character varying(20)",
                oldMaxLength: 20);

            migrationBuilder.AlterColumn<string>(
                name: "DocumentId",
                table: "documents",
                type: "character varying(255)",
                maxLength: 255,
                nullable: false,
                defaultValue: "",
                oldClrType: typeof(string),
                oldType: "character varying(255)",
                oldMaxLength: 255,
                oldNullable: true);

            migrationBuilder.AlterColumn<string>(
                name: "ContentHash",
                table: "documents",
                type: "text",
                nullable: false,
                defaultValue: "",
                oldClrType: typeof(string),
                oldType: "character varying(64)",
                oldMaxLength: 64,
                oldNullable: true);

            migrationBuilder.AddColumn<string>(
                name: "Fingerprint",
                table: "documents",
                type: "character varying(64)",
                maxLength: 64,
                nullable: false,
                defaultValue: "");

            migrationBuilder.CreateIndex(
                name: "IX_documents_DocumentId",
                table: "documents",
                column: "DocumentId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_documents_Fingerprint",
                table: "documents",
                column: "Fingerprint",
                unique: true);
        }
    }
}
