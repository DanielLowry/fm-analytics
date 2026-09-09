using System.Text.Json;
using System.Text.Json.Serialization;
using FMBridge.Data;

var builder = WebApplication.CreateBuilder(args);

builder.WebHost.UseUrls(builder.Configuration["FM_BRIDGE_URL"] ?? "http://localhost:5072");
builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.CamelCase));
});

builder.Services.AddSingleton<IFmDataSource, FixtureFmDataSource>();

var app = builder.Build();

app.MapGet("/health", (IFmDataSource source) => Results.Ok(new
{
    status = "ok",
    source = source.Name,
}));
app.MapGet("/game", async (IFmDataSource source, CancellationToken cancellationToken) =>
    Results.Ok(await source.GetGameAsync(cancellationToken)));
app.MapGet("/squad", async (IFmDataSource source, CancellationToken cancellationToken) =>
    Results.Ok(await source.GetSquadAsync(cancellationToken)));

app.Run();
