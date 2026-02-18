# GABI Worker - Dockerfile
# Build para Fly.io / servidor próprio. Em prod, prefira não assar sources na imagem
# (use volume ou URL e GABI_SOURCES_PATH).

# Build stage
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

# Copy solution and project files first for better layer caching
COPY GabiSync.sln .
COPY src/Gabi.Contracts/Gabi.Contracts.csproj src/Gabi.Contracts/
COPY src/Gabi.Discover/Gabi.Discover.csproj src/Gabi.Discover/
COPY src/Gabi.Ingest/Gabi.Ingest.csproj src/Gabi.Ingest/
COPY src/Gabi.Postgres/Gabi.Postgres.csproj src/Gabi.Postgres/
COPY src/Gabi.Sync/Gabi.Sync.csproj src/Gabi.Sync/
COPY src/Gabi.Worker/Gabi.Worker.csproj src/Gabi.Worker/

# Restore dependencies
RUN dotnet restore src/Gabi.Worker/Gabi.Worker.csproj

# Copy source code
COPY src/ src/

# Build and publish
RUN dotnet publish src/Gabi.Worker/Gabi.Worker.csproj \
    -c Release \
    -o /app/publish \
    /p:UseAppHost=false

# Runtime: aspnet (necessário para Hangfire.AspNetCore)
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends procps curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN adduser --disabled-password --gecos "" gabi

# App publicada (framework-dependent)
COPY --from=build /app/publish .

# Sources: na imagem para compatibilidade; em prod pode sobrescrever com volume
COPY sources_v2.yaml .

# Change ownership
RUN chown -R gabi:gabi /app
USER gabi

# Health: processo ativo (Fly usa isso para manter a machine)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD pgrep -f "dotnet Gabi.Worker.dll" >/dev/null || exit 1

ENTRYPOINT ["dotnet", "Gabi.Worker.dll"]
