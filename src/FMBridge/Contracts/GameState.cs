namespace FMBridge.Contracts;

public sealed record ClubSummary(string Id, string Name);

public sealed record ManagerSummary(string Id, string Name);

public sealed record GameState(
    DateOnly GameDate,
    ManagerSummary HumanManager,
    ClubSummary? ControlledClub);
