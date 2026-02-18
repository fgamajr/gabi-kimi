using System.Text.Json;
using Gabi.Contracts.Fetch;
using Microsoft.Extensions.Logging;

namespace Gabi.Fetch;

/// <summary>
/// Maps CSV row fields to document structure using sources_v2.yaml mapping config.
/// </summary>
public class MappingEngine
{
    private readonly ILogger<MappingEngine>? _logger;

    public MappingEngine(ILogger<MappingEngine>? logger = null)
    {
        _logger = logger;
    }

    /// <summary>
    /// Map CSV fields to a document using the parse.fields configuration.
    /// </summary>
    public MappedDocument Map(
        Dictionary<string, string> csvFields,
        JsonElement parseConfig,
        string sourceId,
        string url)
    {
        var fieldsConfig = parseConfig.GetProperty("fields");
        
        var documentId = ExtractField(csvFields, fieldsConfig, "document_id") 
            ?? throw new InvalidOperationException("document_id is required but not found");
        
        var content = ExtractField(csvFields, fieldsConfig, "content");
        var title = ExtractField(csvFields, fieldsConfig, "title") 
            ?? ExtractField(csvFields, fieldsConfig, "year") ?? sourceId;
        
        var metadata = ExtractMetadata(csvFields, fieldsConfig);
        var textFields = ExtractTextFields(csvFields, fieldsConfig);

        return new MappedDocument(
            DocumentId: documentId,
            Title: title,
            Content: content,
            ContentPreview: content?.Length > 500 ? content[..500] : content,
            Metadata: metadata,
            TextFields: textFields,
            SourceId: sourceId,
            Url: url
        );
    }

    private string? ExtractField(
        Dictionary<string, string> csvFields,
        JsonElement fieldsConfig,
        string fieldName)
    {
        if (!fieldsConfig.TryGetProperty(fieldName, out var fieldConfig))
            return null;

        if (fieldConfig.ValueKind == JsonValueKind.Object)
        {
            var source = fieldConfig.GetProperty("source").GetString();
            if (source == null || !csvFields.TryGetValue(source, out var rawValue))
                return null;

            var transforms = GetTransforms(fieldConfig);
            return Transforms.ApplyChain(rawValue, transforms);
        }

        return null;
    }

    private Dictionary<string, object> ExtractMetadata(
        Dictionary<string, string> csvFields,
        JsonElement fieldsConfig)
    {
        var metadata = new Dictionary<string, object>();

        if (!fieldsConfig.TryGetProperty("metadata", out var metadataConfig))
            return metadata;

        foreach (var prop in metadataConfig.EnumerateObject())
        {
            var value = ExtractFieldValue(csvFields, prop.Value);
            if (value != null)
            {
                metadata[prop.Name] = value;
            }
        }

        return metadata;
    }

    private Dictionary<string, string> ExtractTextFields(
        Dictionary<string, string> csvFields,
        JsonElement fieldsConfig)
    {
        var textFields = new Dictionary<string, string>();

        foreach (var prop in fieldsConfig.EnumerateObject())
        {
            if (prop.Name.StartsWith("text_") || prop.Name == "content")
            {
                var value = ExtractFieldValue(csvFields, prop.Value);
                if (!string.IsNullOrEmpty(value))
                {
                    textFields[prop.Name] = value;
                }
            }
        }

        return textFields;
    }

    private string? ExtractFieldValue(
        Dictionary<string, string> csvFields,
        JsonElement fieldConfig)
    {
        if (fieldConfig.ValueKind != JsonValueKind.Object)
            return null;

        if (!fieldConfig.TryGetProperty("source", out var sourceProp))
            return null;

        var source = sourceProp.GetString();
        if (source == null || !csvFields.TryGetValue(source, out var rawValue))
            return null;

        var transforms = GetTransforms(fieldConfig);
        return Transforms.ApplyChain(rawValue, transforms);
    }

    private static List<string> GetTransforms(JsonElement fieldConfig)
    {
        var transforms = new List<string>();

        if (fieldConfig.TryGetProperty("transforms", out var transformsProp) 
            && transformsProp.ValueKind == JsonValueKind.Array)
        {
            foreach (var t in transformsProp.EnumerateArray())
            {
                var transform = t.GetString();
                if (transform != null)
                {
                    transforms.Add(transform);
                }
            }
        }

        return transforms;
    }
}

/// <summary>
/// Result of mapping a CSV row to a document.
/// </summary>
public record MappedDocument(
    string DocumentId,
    string? Title,
    string? Content,
    string? ContentPreview,
    Dictionary<string, object> Metadata,
    Dictionary<string, string> TextFields,
    string SourceId,
    string Url
);
