namespace FMBridge.Data;

public sealed class FmSourceUnavailableException : Exception
{
    public FmSourceUnavailableException(string status, string message)
        : base(message)
    {
        Status = status;
    }

    public string Status { get; }
}
