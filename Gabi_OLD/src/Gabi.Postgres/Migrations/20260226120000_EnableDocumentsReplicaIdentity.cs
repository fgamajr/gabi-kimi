using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Gabi.Postgres.Migrations
{
    /// <summary>
    /// Enables REPLICA IDENTITY FULL on documents table for WAL logical replication.
    /// Slot and publication creation are handled by WalProjectionBootstrapService (cannot run in a transaction).
    /// </summary>
    [Microsoft.EntityFrameworkCore.Infrastructure.DbContext(typeof(GabiDbContext))]
    [Migration("20260226120000_EnableDocumentsReplicaIdentity")]
    public partial class EnableDocumentsReplicaIdentity : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // REPLICA IDENTITY FULL is safe inside a transaction
            migrationBuilder.Sql("ALTER TABLE documents REPLICA IDENTITY FULL;");

            // Seed the projection checkpoint row (idempotent)
            migrationBuilder.Sql("""
                INSERT INTO projection_checkpoint ("SlotName", "Lsn", "UpdatedAt")
                VALUES ('gabi_projection', '0/0', now())
                ON CONFLICT ("SlotName") DO NOTHING;
                """);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql("ALTER TABLE documents REPLICA IDENTITY DEFAULT;");
        }
    }
}
