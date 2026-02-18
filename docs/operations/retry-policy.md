# Retry Policy

## Source Of Truth

Hangfire retries in Worker are configured in:

- `src/Gabi.Worker/appsettings.json`
- `src/Gabi.Worker/appsettings.Development.json`
- Section: `Hangfire:RetryPolicy`

Example:

```json
{
  "Hangfire": {
    "RetryPolicy": {
      "Attempts": 3,
      "DelaysInSeconds": [2, 8, 30]
    }
  }
}
```

## Runtime Wiring

- `src/Gabi.Worker/Program.cs`
  - Removes default Hangfire `AutomaticRetry` filter.
  - Adds one global `AutomaticRetryAttribute` using `Hangfire:RetryPolicy`.
  - Registers `DlqFilter`.
- `src/Gabi.Worker/Jobs/DlqFilter.cs`
  - Uses `HangfireRetryPolicyOptions` to decide when retries are exhausted and DLQ should be used.
- `src/Gabi.Worker/Jobs/GabiJobRunner.cs`
  - Does not use method-level `AutomaticRetry` attribute.

## Expected Behavior

For `Attempts = 3`:

1. Hangfire retries failed jobs up to 3 attempts.
2. After retries are exhausted, job remains failed.
3. `DlqFilter` moves exhausted jobs to `dlq_entries`.

This prevents divergent retry values between runner and filter paths.
