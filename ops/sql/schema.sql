-- SQL Server Schema for GABI DOU
-- Compatible with SQL Server 2016+ (JSON support)

CREATE TABLE [dbo].[DouDocuments] (
    [Id] NVARCHAR(255) NOT NULL PRIMARY KEY,
    [SourceId] NVARCHAR(255) NOT NULL,
    [PubDate] DATE NOT NULL,
    [Section] NVARCHAR(50),
    [Edition] NVARCHAR(50),
    [Page] INT,
    [ArtType] NVARCHAR(255),
    [Orgao] NVARCHAR(500),
    [Identifica] NVARCHAR(MAX),
    [Ementa] NVARCHAR(MAX),
    [Texto] NVARCHAR(MAX),
    [DataText] NVARCHAR(255),
    [MetadataJson] NVARCHAR(MAX), -- Stores origin_file, processing_version
    [EnrichmentJson] NVARCHAR(MAX), -- Stores summary, tags, score
    [ReferencesJson] NVARCHAR(MAX), -- Stores citations, revocations
    [ImagesJson] NVARCHAR(MAX), -- Stores image paths and metadata
    [CreatedAt] DATETIME2 DEFAULT GETDATE()
);

-- Indexes for common searches
CREATE INDEX [IX_DouDocuments_PubDate] ON [dbo].[DouDocuments] ([PubDate]);
CREATE INDEX [IX_DouDocuments_Section] ON [dbo].[DouDocuments] ([Section]);
CREATE INDEX [IX_DouDocuments_ArtType] ON [dbo].[DouDocuments] ([ArtType]);
