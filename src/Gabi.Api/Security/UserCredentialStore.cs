using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Gabi.Api.Security;

public interface IUserCredentialStore
{
    bool TryValidate(string username, string password, out string role);
}

public sealed class UserCredentialStore : IUserCredentialStore
{
    private readonly IReadOnlyDictionary<string, UserRecord> _users;

    public UserCredentialStore(IConfiguration configuration, IHostEnvironment environment, ILogger<UserCredentialStore> logger)
    {
        var configuredUsers = LoadUsers(configuration);

        if (configuredUsers.Count == 0)
        {
            if (!environment.IsDevelopment())
            {
                throw new InvalidOperationException(
                    "No users configured. Set GABI_USERS with bcrypt password hashes before starting in non-development environments.");
            }

            configuredUsers = CreateDevelopmentFallbackUsers(logger);
        }

        _users = configuredUsers
            .GroupBy(u => u.Username, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(g => g.Key, g => g.Last(), StringComparer.OrdinalIgnoreCase);
    }

    public bool TryValidate(string username, string password, out string role)
    {
        role = string.Empty;
        if (string.IsNullOrWhiteSpace(username) || string.IsNullOrWhiteSpace(password))
            return false;

        if (!_users.TryGetValue(username, out var user))
            return false;

        var ok = false;
        try
        {
            ok = BCrypt.Net.BCrypt.Verify(password, user.PasswordHash);
        }
        catch
        {
            ok = false;
        }

        if (!ok)
            return false;

        role = user.Role;
        return true;
    }

    private static List<UserRecord> LoadUsers(IConfiguration configuration)
    {
        var fromEnv = configuration["GABI_USERS"];
        if (!string.IsNullOrWhiteSpace(fromEnv))
        {
            var parsed = DeserializeUsers(fromEnv);
            if (parsed.Count > 0)
                return parsed;
        }

        var sectionUsers = configuration.GetSection("Gabi:Users").Get<List<UserRecord>>();
        return sectionUsers?.Where(IsValid).ToList() ?? new List<UserRecord>();
    }

    private static List<UserRecord> DeserializeUsers(string json)
    {
        try
        {
            var users = JsonSerializer.Deserialize<List<UserRecord>>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            });
            return users?.Where(IsValid).ToList() ?? new List<UserRecord>();
        }
        catch
        {
            return new List<UserRecord>();
        }
    }

    private static bool IsValid(UserRecord user) =>
        !string.IsNullOrWhiteSpace(user.Username) &&
        !string.IsNullOrWhiteSpace(user.PasswordHash) &&
        !string.IsNullOrWhiteSpace(user.Role);

    private static List<UserRecord> CreateDevelopmentFallbackUsers(ILogger logger)
    {
        var users = new List<(string Username, string Role)>
        {
            ("admin", "Admin"),
            ("operator", "Operator"),
            ("viewer", "Viewer")
        };

        var result = new List<UserRecord>(users.Count);
        foreach (var (username, role) in users)
        {
            var randomPassword = GenerateStrongPassword();
            var hash = BCrypt.Net.BCrypt.HashPassword(randomPassword);
            logger.LogWarning("Development fallback user created: {Username} role={Role} password={Password}", username, role, randomPassword);
            result.Add(new UserRecord(username, hash, role));
        }

        return result;
    }

    private static string GenerateStrongPassword()
    {
        Span<byte> bytes = stackalloc byte[24];
        RandomNumberGenerator.Fill(bytes);
        return Convert.ToBase64String(bytes).TrimEnd('=');
    }

    public sealed record UserRecord(
        [property: JsonPropertyName("username")] string Username,
        [property: JsonPropertyName("password_hash")] string PasswordHash,
        [property: JsonPropertyName("role")] string Role);
}
