using System;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Gabi.Postgres.Migrations
{
    [DbContext(typeof(GabiDbContext))]
    [Migration("20260225140000_AddReconciliationRecords")]
    public partial class AddReconciliationRecords : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "reconciliation_records",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    RunId = table.Column<Guid>(type: "uuid", nullable: false),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    PgActiveCount = table.Column<int>(type: "integer", nullable: false),
                    IndexActiveCount = table.Column<int>(type: "integer", nullable: false),
                    DriftRatio = table.Column<double>(type: "double precision", nullable: false),
                    Status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    ReconciledAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_reconciliation_records", x => x.Id);
                });

            migrationBuilder.CreateIndex(
                name: "IX_reconciliation_records_RunId",
                table: "reconciliation_records",
                column: "RunId");

            migrationBuilder.CreateIndex(
                name: "IX_reconciliation_records_SourceId",
                table: "reconciliation_records",
                column: "SourceId");

            migrationBuilder.CreateIndex(
                name: "IX_reconciliation_records_ReconciledAt",
                table: "reconciliation_records",
                column: "ReconciledAt");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "reconciliation_records");
        }
    }
}
