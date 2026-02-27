namespace Gabi.Api.Models;

/// <summary>Request body for POST /api/v1/admin/sources/{sourceId}/repair-projection</summary>
public record RepairProjectionRequest(
    /// <summary>
    /// When true, resets status to 'pending_projection' for documents missing an ElasticsearchId.
    /// </summary>
    bool ResetStatus = false);
