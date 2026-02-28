using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace Gabi.Postgres.Migrations
{
    /// <inheritdoc />
    [Microsoft.EntityFrameworkCore.Infrastructure.DbContext(typeof(GabiDbContext))]
    [Migration("20260226110000_AddWorkflowTrackingTables")]
    public partial class AddWorkflowTrackingTables : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // Stage history (append-only, best-effort)
            migrationBuilder.CreateTable(
                name: "workflow_events",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false, defaultValueSql: "gen_random_uuid()"),
                    CorrelationId = table.Column<Guid>(type: "uuid", nullable: false),
                    JobId = table.Column<Guid>(type: "uuid", nullable: false),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    JobType = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    EventType = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    Metadata = table.Column<string>(type: "jsonb", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_workflow_events", x => x.Id);
                });

            migrationBuilder.CreateIndex(
                name: "IX_workflow_events_correlation",
                table: "workflow_events",
                column: "CorrelationId");

            migrationBuilder.CreateIndex(
                name: "IX_workflow_events_source",
                table: "workflow_events",
                columns: new[] { "SourceId", "CreatedAt" });

            // WAL projection DLQ (receives failed WAL events for manual replay only)
            migrationBuilder.CreateTable(
                name: "projection_dlq",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    DocumentId = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    Operation = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    Payload = table.Column<string>(type: "jsonb", nullable: false),
                    Error = table.Column<string>(type: "text", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()"),
                    ReplayedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    Status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false, defaultValue: "pending")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_projection_dlq", x => x.Id);
                });

            migrationBuilder.CreateIndex(
                name: "IX_projection_dlq_status",
                table: "projection_dlq",
                columns: new[] { "Status", "Id" },
                filter: "\"Status\" = 'pending'");

            // WAL projection checkpoint (LSN persistence)
            migrationBuilder.CreateTable(
                name: "projection_checkpoint",
                columns: table => new
                {
                    SlotName = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    Lsn = table.Column<string>(type: "text", nullable: false, defaultValue: "0/0"),
                    UpdatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false, defaultValueSql: "now()")
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_projection_checkpoint", x => x.SlotName);
                });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(name: "workflow_events");
            migrationBuilder.DropTable(name: "projection_dlq");
            migrationBuilder.DropTable(name: "projection_checkpoint");
        }
    }
}
