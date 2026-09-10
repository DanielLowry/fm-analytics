using System.Text.Json;
using System.Text.Json.Serialization;
using FMBridge.Data;

var builder = WebApplication.CreateBuilder(args);

builder.WebHost.UseUrls(builder.Configuration["FM_BRIDGE_URL"] ?? "http://localhost:5072");
builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.CamelCase));
});

var sourceName = builder.Configuration["FM_BRIDGE_SOURCE"] ?? "fixture";
switch (sourceName)
{
    case "fixture":
        builder.Services.AddSingleton<IFmDataSource, FixtureFmDataSource>();
        break;
    case "linux-proton":
        builder.Services.AddSingleton<IFmDataSource, LinuxProtonFmDataSource>();
        break;
    default:
        throw new InvalidOperationException(
            $"Unsupported FM_BRIDGE_SOURCE '{sourceName}'. Use 'fixture' or 'linux-proton'.");
}

var app = builder.Build();

app.MapGet("/health", async (IFmDataSource source, CancellationToken cancellationToken) =>
{
    var health = await source.GetHealthAsync(cancellationToken);
    return Results.Json(health, statusCode: health.IsReady ? StatusCodes.Status200OK : StatusCodes.Status503ServiceUnavailable);
});
app.MapGet("/game", GetGameAsync);
app.MapGet("/squad", GetSquadAsync);

app.Run();

static async Task<IResult> GetGameAsync(
    IFmDataSource source,
    CancellationToken cancellationToken)
{
    try
    {
        return Results.Ok(await source.GetGameAsync(cancellationToken));
    }
    catch (FmSourceUnavailableException exception)
    {
        return SourceUnavailable(exception);
    }
}

static async Task<IResult> GetSquadAsync(
    IFmDataSource source,
    CancellationToken cancellationToken)
{
    try
    {
        return Results.Ok(await source.GetSquadAsync(cancellationToken));
    }
    catch (FmSourceUnavailableException exception)
    {
        return SourceUnavailable(exception);
    }
}

static IResult SourceUnavailable(FmSourceUnavailableException exception)
{
    return Results.Json(
        new { status = exception.Status, error = exception.Message },
        statusCode: StatusCodes.Status503ServiceUnavailable);
}
