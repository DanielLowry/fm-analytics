using FMBridge.Contracts;

namespace FMBridge.Data;

public interface IFmDataSource
{
    string Name { get; }

    Task<SourceHealth> GetHealthAsync(CancellationToken cancellationToken);

    Task<GameState> GetGameAsync(CancellationToken cancellationToken);

    Task<Squad> GetSquadAsync(CancellationToken cancellationToken);
}
