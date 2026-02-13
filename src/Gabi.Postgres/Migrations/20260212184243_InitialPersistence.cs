using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace Gabi.Postgres.Migrations
{
    /// <inheritdoc />
    public partial class InitialPersistence : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "audit_log",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    EventType = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    EntityType = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    EntityId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    ActorType = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    ActorId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    Action = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    OldValues = table.Column<string>(type: "jsonb", nullable: true),
                    NewValues = table.Column<string>(type: "jsonb", nullable: true),
                    ChangeSummary = table.Column<string>(type: "text", nullable: true),
                    OccurredAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    RequestId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    SourceIp = table.Column<string>(type: "text", nullable: true),
                    UserAgent = table.Column<string>(type: "text", nullable: true),
                    Metadata = table.Column<string>(type: "jsonb", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_audit_log", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "documents",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    DocumentId = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    Title = table.Column<string>(type: "character varying(1000)", maxLength: 1000, nullable: false),
                    ContentPreview = table.Column<string>(type: "text", nullable: false),
                    Fingerprint = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    ContentHash = table.Column<string>(type: "text", nullable: false),
                    Status = table.Column<int>(type: "integer", maxLength: 20, nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    UpdatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_documents", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "source_registry",
                columns: table => new
                {
                    Id = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    Name = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    Description = table.Column<string>(type: "text", nullable: true),
                    Provider = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    Domain = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    Jurisdiction = table.Column<string>(type: "character varying(10)", maxLength: 10, nullable: true),
                    Category = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: true),
                    CanonicalType = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: true),
                    DiscoveryStrategy = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    DiscoveryConfig = table.Column<string>(type: "jsonb", nullable: false),
                    FetchProtocol = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false, defaultValue: "https"),
                    FetchConfig = table.Column<string>(type: "jsonb", nullable: true),
                    PipelineConfig = table.Column<string>(type: "jsonb", nullable: true),
                    Enabled = table.Column<bool>(type: "boolean", nullable: false),
                    LastRefresh = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    TotalLinks = table.Column<int>(type: "integer", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    UpdatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CreatedBy = table.Column<string>(type: "text", nullable: false),
                    UpdatedBy = table.Column<string>(type: "text", nullable: false),
                    xmin = table.Column<uint>(type: "xid", rowVersion: true, nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_source_registry", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "discovered_links",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    Url = table.Column<string>(type: "text", nullable: false),
                    UrlHash = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    FirstSeenAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    DiscoveredAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    Etag = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: true),
                    LastModified = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    ContentLength = table.Column<long>(type: "bigint", nullable: true),
                    Status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    LastProcessedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    ProcessAttempts = table.Column<int>(type: "integer", nullable: false),
                    MaxAttempts = table.Column<int>(type: "integer", nullable: false),
                    ContentHash = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    LastContentHash = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: true),
                    Metadata = table.Column<string>(type: "jsonb", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    UpdatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CreatedBy = table.Column<string>(type: "text", nullable: false),
                    UpdatedBy = table.Column<string>(type: "text", nullable: false),
                    xmin = table.Column<uint>(type: "xid", rowVersion: true, nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_discovered_links", x => x.Id);
                    table.ForeignKey(
                        name: "FK_discovered_links_source_registry_SourceId",
                        column: x => x.SourceId,
                        principalTable: "source_registry",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "source_refresh",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    StartedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CompletedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    Status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    LinksDiscovered = table.Column<int>(type: "integer", nullable: false),
                    LinksNew = table.Column<int>(type: "integer", nullable: false),
                    LinksUpdated = table.Column<int>(type: "integer", nullable: false),
                    LinksRemoved = table.Column<int>(type: "integer", nullable: false),
                    ErrorMessage = table.Column<string>(type: "text", nullable: true),
                    ErrorDetails = table.Column<string>(type: "jsonb", nullable: true),
                    DurationMs = table.Column<int>(type: "integer", nullable: true),
                    PeakMemoryMb = table.Column<int>(type: "integer", nullable: true),
                    TriggeredBy = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    RequestId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    WorkerId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    HeartbeatAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    UpdatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CreatedBy = table.Column<string>(type: "text", nullable: false),
                    UpdatedBy = table.Column<string>(type: "text", nullable: false),
                    xmin = table.Column<uint>(type: "xid", rowVersion: true, nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_source_refresh", x => x.Id);
                    table.ForeignKey(
                        name: "FK_source_refresh_source_registry_SourceId",
                        column: x => x.SourceId,
                        principalTable: "source_registry",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "ingest_jobs",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    JobType = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    Payload = table.Column<string>(type: "jsonb", nullable: false),
                    PayloadHash = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    LinkId = table.Column<long>(type: "bigint", nullable: true),
                    SourceId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    Status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    Priority = table.Column<int>(type: "integer", nullable: false),
                    ScheduledAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    StartedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    CompletedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    Attempts = table.Column<int>(type: "integer", nullable: false),
                    MaxAttempts = table.Column<int>(type: "integer", nullable: false),
                    LastError = table.Column<string>(type: "text", nullable: true),
                    ErrorDetails = table.Column<string>(type: "jsonb", nullable: true),
                    RetryAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    WorkerId = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    LockedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    LockExpiresAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    ProgressPercent = table.Column<int>(type: "integer", nullable: true),
                    ProgressMessage = table.Column<string>(type: "text", nullable: true),
                    LinksDiscovered = table.Column<int>(type: "integer", nullable: false),
                    Result = table.Column<string>(type: "jsonb", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    UpdatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CreatedBy = table.Column<string>(type: "text", nullable: false),
                    UpdatedBy = table.Column<string>(type: "text", nullable: false),
                    xmin = table.Column<uint>(type: "xid", rowVersion: true, nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_ingest_jobs", x => x.Id);
                    table.ForeignKey(
                        name: "FK_ingest_jobs_discovered_links_LinkId",
                        column: x => x.LinkId,
                        principalTable: "discovered_links",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.SetNull);
                    table.ForeignKey(
                        name: "FK_ingest_jobs_source_registry_SourceId",
                        column: x => x.SourceId,
                        principalTable: "source_registry",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.SetNull);
                });

            migrationBuilder.CreateIndex(
                name: "IX_audit_log_ActorType_ActorId_OccurredAt",
                table: "audit_log",
                columns: new[] { "ActorType", "ActorId", "OccurredAt" });

            migrationBuilder.CreateIndex(
                name: "IX_audit_log_EntityType_EntityId_OccurredAt",
                table: "audit_log",
                columns: new[] { "EntityType", "EntityId", "OccurredAt" });

            migrationBuilder.CreateIndex(
                name: "IX_audit_log_EventType_OccurredAt",
                table: "audit_log",
                columns: new[] { "EventType", "OccurredAt" });

            migrationBuilder.CreateIndex(
                name: "IX_audit_log_OccurredAt",
                table: "audit_log",
                column: "OccurredAt");

            migrationBuilder.CreateIndex(
                name: "IX_audit_log_RequestId",
                table: "audit_log",
                column: "RequestId");

            migrationBuilder.CreateIndex(
                name: "IX_discovered_links_ContentHash",
                table: "discovered_links",
                column: "ContentHash");

            migrationBuilder.CreateIndex(
                name: "IX_discovered_links_DiscoveredAt",
                table: "discovered_links",
                column: "DiscoveredAt");

            migrationBuilder.CreateIndex(
                name: "IX_discovered_links_Metadata",
                table: "discovered_links",
                column: "Metadata")
                .Annotation("Npgsql:IndexMethod", "GIN");

            migrationBuilder.CreateIndex(
                name: "IX_discovered_links_SourceId_Status",
                table: "discovered_links",
                columns: new[] { "SourceId", "Status" });

            migrationBuilder.CreateIndex(
                name: "IX_discovered_links_SourceId_UrlHash",
                table: "discovered_links",
                columns: new[] { "SourceId", "UrlHash" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_documents_DocumentId",
                table: "documents",
                column: "DocumentId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_documents_Fingerprint",
                table: "documents",
                column: "Fingerprint",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_documents_SourceId",
                table: "documents",
                column: "SourceId");

            migrationBuilder.CreateIndex(
                name: "idx_jobs_available",
                table: "ingest_jobs",
                columns: new[] { "Status", "Priority", "ScheduledAt", "CreatedAt" });

            migrationBuilder.CreateIndex(
                name: "IX_ingest_jobs_LinkId",
                table: "ingest_jobs",
                column: "LinkId");

            migrationBuilder.CreateIndex(
                name: "IX_ingest_jobs_PayloadHash",
                table: "ingest_jobs",
                column: "PayloadHash",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_ingest_jobs_RetryAt",
                table: "ingest_jobs",
                column: "RetryAt");

            migrationBuilder.CreateIndex(
                name: "IX_ingest_jobs_SourceId",
                table: "ingest_jobs",
                column: "SourceId");

            migrationBuilder.CreateIndex(
                name: "IX_ingest_jobs_Status_WorkerId_LockedAt",
                table: "ingest_jobs",
                columns: new[] { "Status", "WorkerId", "LockedAt" });

            migrationBuilder.CreateIndex(
                name: "IX_source_refresh_SourceId_StartedAt",
                table: "source_refresh",
                columns: new[] { "SourceId", "StartedAt" });

            migrationBuilder.CreateIndex(
                name: "IX_source_refresh_Status_HeartbeatAt",
                table: "source_refresh",
                columns: new[] { "Status", "HeartbeatAt" });

            migrationBuilder.CreateIndex(
                name: "IX_source_registry_Category",
                table: "source_registry",
                column: "Category");

            migrationBuilder.CreateIndex(
                name: "IX_source_registry_Enabled",
                table: "source_registry",
                column: "Enabled");

            migrationBuilder.CreateIndex(
                name: "IX_source_registry_Provider",
                table: "source_registry",
                column: "Provider");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "audit_log");

            migrationBuilder.DropTable(
                name: "documents");

            migrationBuilder.DropTable(
                name: "ingest_jobs");

            migrationBuilder.DropTable(
                name: "source_refresh");

            migrationBuilder.DropTable(
                name: "discovered_links");

            migrationBuilder.DropTable(
                name: "source_registry");
        }
    }
}
