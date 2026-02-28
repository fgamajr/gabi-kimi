namespace Gabi.Postgres.Tests;

/// <summary>
/// CODEX-D: validates drift ratio and status convention (10 pg, 8 index → DriftRatio 0.2 → drifted).
/// </summary>
public class ReconciliationRecordDriftTests
{
    private const double MaxDrift = 0.1;

    [Fact]
    public void DriftRatio_10Pg8Index_Is0_2()
    {
        int pgActiveCount = 10;
        int indexActiveCount = 8;
        var driftRatio = pgActiveCount == 0 ? 0.0 : Math.Abs(pgActiveCount - indexActiveCount) / (double)pgActiveCount;
        Assert.Equal(0.2, driftRatio);
    }

    [Fact]
    public void Status_WhenDriftRatio0_2_AndMaxDrift0_1_IsDrifted()
    {
        int pgActiveCount = 10;
        int indexActiveCount = 8;
        var driftRatio = pgActiveCount == 0 ? 0.0 : Math.Abs(pgActiveCount - indexActiveCount) / (double)pgActiveCount;
        var status = driftRatio <= MaxDrift ? "ok" : "drifted";
        Assert.Equal("drifted", status);
    }
}
