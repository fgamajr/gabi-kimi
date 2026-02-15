using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Gabi.Postgres.Migrations
{
    /// <inheritdoc />
    public partial class AddDiscoveryRunsAndPhaseTracking : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "discovery_runs",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    JobId = table.Column<Guid>(type: "uuid", nullable: false),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    StartedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CompletedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    LinksTotal = table.Column<int>(type: "integer", nullable: false),
                    Status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    ErrorSummary = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_discovery_runs", x => x.Id);
                });

            migrationBuilder.CreateIndex(name: "IX_discovery_runs_CompletedAt", table: "discovery_runs", column: "CompletedAt");
            migrationBuilder.CreateIndex(name: "IX_discovery_runs_JobId", table: "discovery_runs", column: "JobId");
            migrationBuilder.CreateIndex(name: "IX_discovery_runs_SourceId", table: "discovery_runs", column: "SourceId");

            migrationBuilder.AddColumn<string>(
                name: "DiscoveryStatus",
                table: "discovered_links",
                type: "character varying(20)",
                maxLength: 20,
                nullable: false,
                defaultValue: "completed");

            migrationBuilder.AddColumn<string>(
                name: "FetchStatus",
                table: "discovered_links",
                type: "character varying(20)",
                maxLength: 20,
                nullable: false,
                defaultValue: "pending");

            migrationBuilder.AddColumn<string>(
                name: "IngestStatus",
                table: "discovered_links",
                type: "character varying(20)",
                maxLength: 20,
                nullable: false,
                defaultValue: "pending");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(name: "discovery_runs");
            migrationBuilder.DropColumn(name: "DiscoveryStatus", table: "discovered_links");
            migrationBuilder.DropColumn(name: "FetchStatus", table: "discovered_links");
            migrationBuilder.DropColumn(name: "IngestStatus", table: "discovered_links");
        }
    }
}
