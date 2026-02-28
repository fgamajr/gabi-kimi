using System;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Gabi.Postgres.Migrations
{
    /// <inheritdoc />
    [DbContext(typeof(GabiDbContext))]
    [Migration("20260225150000_AddSourcePipelineState")]
    public partial class AddSourcePipelineState : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "source_pipeline_state",
                columns: table => new
                {
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    State = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    ActivePhase = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: true),
                    PausedBy = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    PausedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    LastResumedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    UpdatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_source_pipeline_state", x => x.SourceId);
                });

            migrationBuilder.CreateIndex(
                name: "IX_source_pipeline_state_State",
                table: "source_pipeline_state",
                column: "State");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "source_pipeline_state");
        }
    }
}
