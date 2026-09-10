using System.Text.Json;
using System.Text.Json.Serialization;
using FMBridge.Contracts;

namespace FMBridge.Data;

public sealed class FixtureFmDataSource : IFmDataSource
{
    private readonly string _fixturePath;
    private readonly JsonSerializerOptions _options = new(JsonSerializerDefaults.Web)
    {
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) },
    };

    public FixtureFmDataSource(IHostEnvironment environment, IConfiguration configuration)
    {
        _fixturePath = configuration["FM_BRIDGE_FIXTURE"]
            ?? Path.Combine(environment.ContentRootPath, "fixtures", "sample-game.json");
    }

    public string Name => "fixture";

    public Task<SourceHealth> GetHealthAsync(CancellationToken cancellationToken)
    {
        return Task.FromResult(new SourceHealth("ready", Name));
    }

    public async Task<GameState> GetGameAsync(CancellationToken cancellationToken)
    {
        var fixture = await ReadFixtureAsync(cancellationToken);
        return fixture.Game;
    }

    public async Task<Squad> GetSquadAsync(CancellationToken cancellationToken)
    {
        var fixture = await ReadFixtureAsync(cancellationToken);
        return fixture.Squad;
    }

    private async Task<GameFixture> ReadFixtureAsync(CancellationToken cancellationToken)
    {
        await using var stream = File.OpenRead(_fixturePath);
        var fixture = await JsonSerializer.DeserializeAsync<GameFixture>(stream, _options, cancellationToken)
            ?? throw new InvalidDataException($"Fixture '{_fixturePath}' was empty.");
        foreach (var attribute in fixture.Squad.Players.SelectMany(player => player.Attributes.Values))
        {
            attribute.Validate();
        }
        return fixture;
    }

    private sealed record GameFixture(GameState Game, Squad Squad);
}
