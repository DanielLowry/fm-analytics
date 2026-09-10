namespace FMBridge.Contracts;

public sealed record SourceHealth(
    string Status,
    string Source,
    string? Detail = null)
{
    public bool IsReady => Status == "ready";
}
