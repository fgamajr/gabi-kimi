using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace Gabi.Postgres.Migrations
{
    /// <inheritdoc />
    public partial class _20260214120000_AddFetchLayerAndPipelineActions : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<long>(
                name: "FetchItemId",
                table: "ingest_jobs",
                type: "bigint",
                nullable: true);

            migrationBuilder.AddColumn<long>(
                name: "FetchItemId",
                table: "documents",
                type: "bigint",
                nullable: true);

            migrationBuilder.CreateTable(
                name: "fetch_runs",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    JobId = table.Column<Guid>(type: "uuid", nullable: false),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    StartedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CompletedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    ItemsTotal = table.Column<int>(type: "integer", nullable: false),
                    ItemsCompleted = table.Column<int>(type: "integer", nullable: false),
                    ItemsFailed = table.Column<int>(type: "integer", nullable: false),
                    Status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    ErrorSummary = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_fetch_runs", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "pipeline_actions",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    Action = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    Scope = table.Column<string>(type: "character varying(30)", maxLength: 30, nullable: false),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    Params = table.Column<string>(type: "jsonb", nullable: false),
                    Actor = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    At = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_pipeline_actions", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "fetch_items",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    DiscoveredLinkId = table.Column<long>(type: "bigint", nullable: false),
                    FetchRunId = table.Column<Guid>(type: "uuid", nullable: true),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    Url = table.Column<string>(type: "text", nullable: false),
                    UrlHash = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    Status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    Attempts = table.Column<int>(type: "integer", nullable: false),
                    MaxAttempts = table.Column<int>(type: "integer", nullable: false),
                    LastError = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true),
                    StartedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    CompletedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    UpdatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CreatedBy = table.Column<string>(type: "text", nullable: false),
                    UpdatedBy = table.Column<string>(type: "text", nullable: false),
                    xmin = table.Column<uint>(type: "xid", rowVersion: true, nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_fetch_items", x => x.Id);
                    table.ForeignKey(
                        name: "FK_fetch_items_discovered_links_DiscoveredLinkId",
                        column: x => x.DiscoveredLinkId,
                        principalTable: "discovered_links",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_fetch_items_fetch_runs_FetchRunId",
                        column: x => x.FetchRunId,
                        principalTable: "fetch_runs",
                        principalColumn: "Id");
                });

            migrationBuilder.CreateIndex(
                name: "IX_ingest_jobs_FetchItemId",
                table: "ingest_jobs",
                column: "FetchItemId");

            migrationBuilder.CreateIndex(
                name: "IX_documents_FetchItemId",
                table: "documents",
                column: "FetchItemId");

            migrationBuilder.CreateIndex(
                name: "IX_fetch_items_DiscoveredLinkId",
                table: "fetch_items",
                column: "DiscoveredLinkId");

            migrationBuilder.CreateIndex(
                name: "IX_fetch_items_DiscoveredLinkId_UrlHash",
                table: "fetch_items",
                columns: new[] { "DiscoveredLinkId", "UrlHash" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_fetch_items_FetchRunId",
                table: "fetch_items",
                column: "FetchRunId");

            migrationBuilder.CreateIndex(
                name: "IX_fetch_items_SourceId_Status",
                table: "fetch_items",
                columns: new[] { "SourceId", "Status" });

            migrationBuilder.CreateIndex(
                name: "IX_fetch_runs_CompletedAt",
                table: "fetch_runs",
                column: "CompletedAt");

            migrationBuilder.CreateIndex(
                name: "IX_fetch_runs_JobId",
                table: "fetch_runs",
                column: "JobId");

            migrationBuilder.CreateIndex(
                name: "IX_fetch_runs_SourceId",
                table: "fetch_runs",
                column: "SourceId");

            migrationBuilder.CreateIndex(
                name: "IX_pipeline_actions_At",
                table: "pipeline_actions",
                column: "At");

            migrationBuilder.CreateIndex(
                name: "IX_pipeline_actions_SourceId",
                table: "pipeline_actions",
                column: "SourceId");

            migrationBuilder.AddForeignKey(
                name: "FK_documents_fetch_items_FetchItemId",
                table: "documents",
                column: "FetchItemId",
                principalTable: "fetch_items",
                principalColumn: "Id",
                onDelete: ReferentialAction.SetNull);

            migrationBuilder.AddForeignKey(
                name: "FK_ingest_jobs_fetch_items_FetchItemId",
                table: "ingest_jobs",
                column: "FetchItemId",
                principalTable: "fetch_items",
                principalColumn: "Id",
                onDelete: ReferentialAction.SetNull);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropForeignKey(
                name: "FK_documents_fetch_items_FetchItemId",
                table: "documents");

            migrationBuilder.DropForeignKey(
                name: "FK_ingest_jobs_fetch_items_FetchItemId",
                table: "ingest_jobs");

            migrationBuilder.DropTable(
                name: "fetch_items");

            migrationBuilder.DropTable(
                name: "pipeline_actions");

            migrationBuilder.DropTable(
                name: "fetch_runs");

            migrationBuilder.DropIndex(
                name: "IX_ingest_jobs_FetchItemId",
                table: "ingest_jobs");

            migrationBuilder.DropIndex(
                name: "IX_documents_FetchItemId",
                table: "documents");

            migrationBuilder.DropColumn(
                name: "FetchItemId",
                table: "ingest_jobs");

            migrationBuilder.DropColumn(
                name: "FetchItemId",
                table: "documents");
        }
    }
}
