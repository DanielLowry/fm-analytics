namespace FMBridge.Contracts;

public enum AttributeVisibility
{
    Known,
    Range,
    Unknown,
}

public sealed record AttributeObservation
{
    public required AttributeVisibility Visibility { get; init; }
    public int? Value { get; init; }
    public int? Minimum { get; init; }
    public int? Maximum { get; init; }

    public void Validate()
    {
        switch (Visibility)
        {
            case AttributeVisibility.Known when Value is null || Minimum is not null || Maximum is not null:
                throw new InvalidDataException("Known attributes require only an exact value.");
            case AttributeVisibility.Range when Value is not null || Minimum is null || Maximum is null:
                throw new InvalidDataException("Range attributes require only a minimum and maximum.");
            case AttributeVisibility.Range when Minimum > Maximum:
                throw new InvalidDataException("Attribute minimum cannot exceed maximum.");
            case AttributeVisibility.Unknown when Value is not null || Minimum is not null || Maximum is not null:
                throw new InvalidDataException("Unknown attributes cannot contain values.");
        }
    }
}

public sealed record Player(
    string Id,
    string Name,
    int Age,
    IReadOnlyList<string> Positions,
    string ClubId,
    IReadOnlyDictionary<string, AttributeObservation> Attributes);

public sealed record Squad(
    ClubSummary Club,
    DateOnly AsOfDate,
    IReadOnlyList<Player> Players);
