namespace Gabi.Api.Security;

public sealed class LocalMediaPathValidator
{
    private readonly string _basePath;

    public LocalMediaPathValidator(IConfiguration configuration)
    {
        var configured = configuration["Gabi:Media:BasePath"];
        _basePath = string.IsNullOrWhiteSpace(configured) ? "/workspace/" : configured;
    }

    public bool TryValidate(string requestedPath, out string resolvedPath)
    {
        resolvedPath = string.Empty;

        if (string.IsNullOrWhiteSpace(requestedPath))
            return false;

        if (requestedPath.Contains("..", StringComparison.Ordinal))
            return false;

        try
        {
            var fullBasePath = NormalizeDirectoryPath(Path.GetFullPath(_basePath));
            var candidateFullPath = Path.GetFullPath(requestedPath);

            if (!candidateFullPath.StartsWith(fullBasePath, StringComparison.Ordinal))
                return false;

            if (!File.Exists(candidateFullPath))
                return false;

            var attributes = File.GetAttributes(candidateFullPath);
            if ((attributes & FileAttributes.ReparsePoint) == FileAttributes.ReparsePoint)
            {
                var linkTarget = File.ResolveLinkTarget(candidateFullPath, returnFinalTarget: true);
                if (linkTarget != null)
                {
                    var targetPath = Path.GetFullPath(linkTarget.FullName);
                    if (!targetPath.StartsWith(fullBasePath, StringComparison.Ordinal))
                        return false;
                }
            }

            resolvedPath = candidateFullPath;
            return true;
        }
        catch
        {
            return false;
        }
    }

    private static string NormalizeDirectoryPath(string path)
    {
        if (path.EndsWith(Path.DirectorySeparatorChar))
            return path;

        return path + Path.DirectorySeparatorChar;
    }
}
