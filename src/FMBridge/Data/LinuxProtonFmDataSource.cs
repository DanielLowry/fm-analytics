using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;
using FMBridge.Contracts;

namespace FMBridge.Data;

public sealed class LinuxProtonFmDataSource : IFmDataSource
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly SemaphoreSlim _gate = new(1, 1);
    private readonly string _probePath;
    private readonly string _pythonExecutable;
    private readonly TimeSpan _timeout;
    private ProbeDocument? _cachedDocument;
    private DateTimeOffset _cachedAt;

    public LinuxProtonFmDataSource(IConfiguration configuration)
    {
        _probePath = configuration["FM_BRIDGE_PROBE"]
            ?? Path.Combine(AppContext.BaseDirectory, "tools", "fm20_linux_probe.py");
        _pythonExecutable = configuration["FM_BRIDGE_PYTHON"] ?? "python3";
        var configuredTimeout = int.TryParse(
            configuration["FM_BRIDGE_PROBE_TIMEOUT_SECONDS"],
            out var timeoutSeconds);
        _timeout = TimeSpan.FromSeconds(configuredTimeout ? Math.Clamp(timeoutSeconds, 1, 60) : 10);
    }

    public string Name => "linux-proton";

    public async Task<SourceHealth> GetHealthAsync(CancellationToken cancellationToken)
    {
        try
        {
            await ReadProbeAsync(cancellationToken);
            return new SourceHealth("ready", Name);
        }
        catch (FmSourceUnavailableException exception)
        {
            return new SourceHealth(exception.Status, Name, exception.Message);
        }
    }

    public async Task<GameState> GetGameAsync(CancellationToken cancellationToken)
    {
        var document = await ReadProbeAsync(cancellationToken);
        var manager = ActiveManager(document);
        return new GameState(
            ParseDate(document.GameDate),
            new ManagerSummary(manager.Id, manager.Name),
            MapClub(manager.Club));
    }

    public async Task<Squad> GetSquadAsync(CancellationToken cancellationToken)
    {
        var document = await ReadProbeAsync(cancellationToken);
        var manager = ActiveManager(document);
        var club = MapClub(manager.Club);
        var players = document.FirstTeamSquad
            .Select(player => MapPlayer(player, club?.Id ?? string.Empty))
            .ToArray();
        return new Squad(club, ParseDate(document.GameDate), players);
    }

    private async Task<ProbeDocument> ReadProbeAsync(CancellationToken cancellationToken)
    {
        await _gate.WaitAsync(cancellationToken);
        try
        {
            if (_cachedDocument is not null
                && DateTimeOffset.UtcNow - _cachedAt < TimeSpan.FromSeconds(1))
            {
                return _cachedDocument;
            }

            var document = await RunProbeAsync(cancellationToken);
            Validate(document);
            _cachedDocument = document;
            _cachedAt = DateTimeOffset.UtcNow;
            return document;
        }
        finally
        {
            _gate.Release();
        }
    }

    private async Task<ProbeDocument> RunProbeAsync(CancellationToken cancellationToken)
    {
        if (!File.Exists(_probePath))
        {
            throw new FmSourceUnavailableException(
                "misconfigured",
                $"FM20 probe was not found at '{_probePath}'.");
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = _pythonExecutable,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        startInfo.ArgumentList.Add(_probePath);
        startInfo.ArgumentList.Add("--json");

        using var process = new Process { StartInfo = startInfo };
        try
        {
            if (!process.Start())
            {
                throw new FmSourceUnavailableException(
                    "misconfigured", "The FM20 probe process did not start.");
            }
        }
        catch (FmSourceUnavailableException)
        {
            throw;
        }
        catch (Exception exception) when (exception is InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            throw new FmSourceUnavailableException(
                "misconfigured",
                $"Could not start '{_pythonExecutable}': {exception.Message}");
        }

        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(_timeout);
        var standardOutput = process.StandardOutput.ReadToEndAsync(timeout.Token);
        var standardError = process.StandardError.ReadToEndAsync(timeout.Token);
        try
        {
            await process.WaitForExitAsync(timeout.Token);
        }
        catch (OperationCanceledException)
        {
            TryKill(process);
            if (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            throw new FmSourceUnavailableException(
                "timeout", $"FM20 probe exceeded {_timeout.TotalSeconds:0} seconds.");
        }

        var output = await standardOutput;
        var error = await standardError;
        if (process.ExitCode != 0)
        {
            var detail = string.IsNullOrWhiteSpace(error) ? output : error;
            throw new FmSourceUnavailableException(
                ClassifyFailure(detail), CleanDetail(detail));
        }

        try
        {
            return JsonSerializer.Deserialize<ProbeDocument>(output, JsonOptions)
                ?? throw new JsonException("probe returned an empty document");
        }
        catch (JsonException exception)
        {
            throw new FmSourceUnavailableException(
                "invalid_payload", $"FM20 probe returned invalid JSON: {exception.Message}");
        }
    }

    private static void Validate(ProbeDocument document)
    {
        if (document.HumanManagers is null || document.FirstTeamSquad is null)
        {
            throw new FmSourceUnavailableException(
                "invalid_payload", "Probe response omitted required collections.");
        }
        _ = ParseDate(document.GameDate);

        var activeManagers = document.HumanManagers.Count(manager => manager.Active);
        if (activeManagers != 1)
        {
            throw new FmSourceUnavailableException(
                "save_not_ready", $"Expected one active human manager, found {activeManagers}.");
        }

        var duplicate = document.FirstTeamSquad
            .GroupBy(player => player.Id)
            .FirstOrDefault(group => group.Count() > 1);
        if (duplicate is not null)
        {
            throw new FmSourceUnavailableException(
                "invalid_payload", $"Duplicate player ID '{duplicate.Key}' in first-team squad.");
        }

        foreach (var player in document.FirstTeamSquad)
        {
            ValidatePercent(player.ConditionPercent, player.Id, "condition");
            ValidatePercent(player.MatchFitnessPercent, player.Id, "match fitness");
            if (player.Positions is null || player.Positions.Count == 0)
            {
                throw new FmSourceUnavailableException(
                    "invalid_payload", $"Player '{player.Id}' has no positions.");
            }
        }
    }

    private static ProbeManager ActiveManager(ProbeDocument document)
    {
        return document.HumanManagers.Single(manager => manager.Active);
    }

    private static ClubSummary? MapClub(ProbeClub? club)
    {
        return club is null ? null : new ClubSummary(club.Id, club.Name);
    }

    private static Player MapPlayer(ProbePlayer player, string clubId)
    {
        return new Player(
            player.Id,
            player.Name,
            ParseOptionalDate(player.DateOfBirth),
            player.Age,
            player.Positions,
            clubId,
            player.ConditionPercent,
            player.MatchFitnessPercent,
            player.Availability,
            player.Injured,
            player.Suspended,
            MapContract(player.Contract),
            new Dictionary<string, AttributeObservation>());
    }

    private static PlayerContract? MapContract(ProbeContract? contract)
    {
        return contract is null
            ? null
            : new PlayerContract(
                contract.ContractType,
                ParseOptionalDate(contract.StartDate),
                ParseOptionalDate(contract.EndDate),
                ParseOptionalDate(contract.JoinedDate),
                contract.SquadStatus,
                contract.TransferStatus,
                MapClub(contract.ContractedClub));
    }

    private static DateOnly ParseDate(string value)
    {
        if (DateOnly.TryParseExact(
            value,
            "yyyy-MM-dd",
            CultureInfo.InvariantCulture,
            DateTimeStyles.None,
            out var result))
        {
            return result;
        }
        throw new FmSourceUnavailableException(
            "invalid_payload", $"Probe returned invalid ISO date '{value}'.");
    }

    private static DateOnly? ParseOptionalDate(string? value)
    {
        return value is null ? null : ParseDate(value);
    }

    private static string ClassifyFailure(string detail)
    {
        if (detail.Contains("no running FM20 process", StringComparison.OrdinalIgnoreCase))
        {
            return "game_absent";
        }
        if (detail.Contains("year=1900", StringComparison.OrdinalIgnoreCase))
        {
            return "save_not_loaded";
        }
        if (detail.Contains("multiple FM20 processes", StringComparison.OrdinalIgnoreCase))
        {
            return "ambiguous_process";
        }
        if (detail.Contains("cannot open process", StringComparison.OrdinalIgnoreCase))
        {
            return "permission_denied";
        }
        if (detail.Contains("not a PE image", StringComparison.OrdinalIgnoreCase)
            || detail.Contains("unsupported executable", StringComparison.OrdinalIgnoreCase)
            || detail.Contains("invalid pointer collection", StringComparison.OrdinalIgnoreCase))
        {
            return "incompatible_build";
        }
        return "unavailable";
    }

    private static void ValidatePercent(int? value, string playerId, string field)
    {
        if (value is < 0 or > 100)
        {
            throw new FmSourceUnavailableException(
                "invalid_payload", $"Player '{playerId}' has invalid {field} percentage.");
        }
    }

    private static string CleanDetail(string detail)
    {
        var cleaned = detail.Trim();
        return cleaned.StartsWith("error: ", StringComparison.OrdinalIgnoreCase)
            ? cleaned[7..]
            : cleaned;
    }

    private static void TryKill(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch (InvalidOperationException)
        {
            // The process exited between HasExited and Kill.
        }
    }

    private sealed record ProbeDocument(
        [property: JsonPropertyName("game_date")] string GameDate,
        [property: JsonPropertyName("human_managers")] IReadOnlyList<ProbeManager> HumanManagers,
        [property: JsonPropertyName("first_team_squad")] IReadOnlyList<ProbePlayer> FirstTeamSquad);

    private sealed record ProbeManager(string Id, string Name, ProbeClub? Club, bool Active);

    private sealed record ProbeClub(string Id, string Name);

    private sealed record ProbePlayer(
        string Id,
        string Name,
        [property: JsonPropertyName("date_of_birth")] string? DateOfBirth,
        int? Age,
        IReadOnlyList<string> Positions,
        [property: JsonPropertyName("condition_percent")] int? ConditionPercent,
        [property: JsonPropertyName("match_fitness_percent")] int? MatchFitnessPercent,
        string Availability,
        bool? Injured,
        bool? Suspended,
        ProbeContract? Contract);

    private sealed record ProbeContract(
        [property: JsonPropertyName("contract_type")] string? ContractType,
        [property: JsonPropertyName("start_date")] string? StartDate,
        [property: JsonPropertyName("end_date")] string? EndDate,
        [property: JsonPropertyName("joined_date")] string? JoinedDate,
        [property: JsonPropertyName("squad_status")] string? SquadStatus,
        [property: JsonPropertyName("transfer_status")] string? TransferStatus,
        [property: JsonPropertyName("contracted_club")] ProbeClub? ContractedClub);
}
