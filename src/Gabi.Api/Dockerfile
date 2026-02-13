# GABI API - Dockerfile
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

# Copy solution and project files
COPY GabiSync.sln .
COPY src/Gabi.Contracts/Gabi.Contracts.csproj src/Gabi.Contracts/
COPY src/Gabi.Discover/Gabi.Discover.csproj src/Gabi.Discover/
COPY src/Gabi.Postgres/Gabi.Postgres.csproj src/Gabi.Postgres/
COPY src/Gabi.Api/Gabi.Api.csproj src/Gabi.Api/

# Restore dependencies
RUN dotnet restore src/Gabi.Api/Gabi.Api.csproj

# Copy source code
COPY src/ src/

# Build and publish
RUN dotnet publish src/Gabi.Api/Gabi.Api.csproj \
    -c Release \
    -o /app/publish \
    /p:UseAppHost=false

# Runtime stage
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app

# Create non-root user
RUN adduser --disabled-password --gecos "" gabi

# Copy published app
COPY --from=build /app/publish .

# Change ownership
RUN chown -R gabi:gabi /app
USER gabi

EXPOSE 8080

ENTRYPOINT ["dotnet", "Gabi.Api.dll"]
