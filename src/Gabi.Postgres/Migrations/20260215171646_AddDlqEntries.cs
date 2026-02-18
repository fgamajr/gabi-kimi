using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Gabi.Postgres.Migrations
{
    /// <inheritdoc />
    public partial class AddDlqEntries : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "dlq_entries",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    JobType = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    OriginalJobId = table.Column<Guid>(type: "uuid", nullable: true),
                    HangfireJobId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    Payload = table.Column<string>(type: "jsonb", nullable: true),
                    ErrorMessage = table.Column<string>(type: "character varying(4000)", maxLength: 4000, nullable: true),
                    ErrorType = table.Column<string>(type: "character varying(200)", maxLength: 200, nullable: true),
                    StackTrace = table.Column<string>(type: "jsonb", nullable: true),
                    RetryCount = table.Column<int>(type: "integer", nullable: false),
                    FailedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    ReplayedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    ReplayedBy = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    ReplayedAsJobId = table.Column<Guid>(type: "uuid", nullable: true),
                    Status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    Notes = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_dlq_entries", x => x.Id);
                });

            migrationBuilder.CreateIndex(
                name: "IX_dlq_entries_FailedAt",
                table: "dlq_entries",
                column: "FailedAt");

            migrationBuilder.CreateIndex(
                name: "IX_dlq_entries_JobType",
                table: "dlq_entries",
                column: "JobType");

            migrationBuilder.CreateIndex(
                name: "IX_dlq_entries_ReplayedAt",
                table: "dlq_entries",
                column: "ReplayedAt");

            migrationBuilder.CreateIndex(
                name: "IX_dlq_entries_SourceId",
                table: "dlq_entries",
                column: "SourceId");

            migrationBuilder.CreateIndex(
                name: "IX_dlq_entries_Status",
                table: "dlq_entries",
                column: "Status");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "dlq_entries");
        }
    }
}
