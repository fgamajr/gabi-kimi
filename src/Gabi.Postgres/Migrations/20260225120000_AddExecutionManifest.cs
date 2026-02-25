using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace Gabi.Postgres.Migrations
{
    /// <inheritdoc />
    public partial class AddExecutionManifest : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "execution_manifest",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    DiscoveryRunId = table.Column<Guid>(type: "uuid", nullable: false),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    SnapshotAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    ResolvedParameters = table.Column<string>(type: "jsonb", nullable: true),
                    ExpectedLinkCount = table.Column<int>(type: "integer", nullable: true),
                    ActualLinkCount = table.Column<int>(type: "integer", nullable: false),
                    ActualFetchCount = table.Column<int>(type: "integer", nullable: true),
                    ActualIngestCount = table.Column<int>(type: "integer", nullable: true),
                    ExternalIdSetHash = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    Status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    CoverageRatio = table.Column<decimal>(type: "numeric", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_execution_manifest", x => x.Id);
                });

            migrationBuilder.CreateIndex(
                name: "IX_execution_manifest_DiscoveryRunId",
                table: "execution_manifest",
                column: "DiscoveryRunId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_execution_manifest_SourceId",
                table: "execution_manifest",
                column: "SourceId");

            migrationBuilder.CreateIndex(
                name: "IX_execution_manifest_SnapshotAt",
                table: "execution_manifest",
                column: "SnapshotAt");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "execution_manifest");
        }
    }
}
