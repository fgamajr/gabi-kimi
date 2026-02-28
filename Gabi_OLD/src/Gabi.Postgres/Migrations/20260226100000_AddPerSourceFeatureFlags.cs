using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Gabi.Postgres.Migrations
{
    /// <inheritdoc />
    [Microsoft.EntityFrameworkCore.Infrastructure.DbContext(typeof(GabiDbContext))]
    [Migration("20260226100000_AddPerSourceFeatureFlags")]
    public partial class AddPerSourceFeatureFlags : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<bool>(
                name: "UseTemporalOrchestration",
                table: "source_registry",
                type: "boolean",
                nullable: false,
                defaultValue: false);

            migrationBuilder.AddColumn<bool>(
                name: "UseWalProjection",
                table: "source_registry",
                type: "boolean",
                nullable: false,
                defaultValue: false);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "UseTemporalOrchestration",
                table: "source_registry");

            migrationBuilder.DropColumn(
                name: "UseWalProjection",
                table: "source_registry");
        }
    }
}
