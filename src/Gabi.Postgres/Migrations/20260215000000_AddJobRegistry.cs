using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Gabi.Postgres.Migrations
{
    /// <inheritdoc />
    public partial class AddJobRegistry : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "job_registry",
                columns: table => new
                {
                    JobId = table.Column<Guid>(type: "uuid", nullable: false),
                    HangfireJobId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    JobType = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    Status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    StartedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    CompletedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    ErrorMessage = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true),
                    ProgressPercent = table.Column<int>(type: "integer", nullable: false),
                    ProgressMessage = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_job_registry", x => x.JobId);
                });

            migrationBuilder.CreateIndex("IX_job_registry_SourceId", table: "job_registry", column: "SourceId");
            migrationBuilder.CreateIndex("IX_job_registry_JobType", table: "job_registry", column: "JobType");
            migrationBuilder.CreateIndex("IX_job_registry_CreatedAt", table: "job_registry", column: "CreatedAt");
            migrationBuilder.CreateIndex("IX_job_registry_Status", table: "job_registry", column: "Status");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(name: "job_registry");
        }
    }
}
