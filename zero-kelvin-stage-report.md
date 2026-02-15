# Zero Kelvin Stage Report
Date: 2026-02-14T00:35:22-03:00
Mode: host api+worker + docker infra
Source: tcu_acordaos
## Round 1 - After Seed
```
discovered_links|0
discovery_runs|0
documents|0
fetch_items|0
fetch_runs|0
ingest_jobs|1
seed_runs|1
source_registry|13
(8 rows)
--
ingest_jobs.status.completed|1
(1 row)
```
## Round 1 - After Discovery
```
discovered_links|0
discovery_runs|1
documents|0
fetch_items|0
fetch_runs|0
ingest_jobs|2
seed_runs|1
source_registry|13
(8 rows)
--
discovery_runs.status.failed|1
ingest_jobs.status.completed|1
ingest_jobs.status.processing|1
(3 rows)
```
## Round 1 - After Fetch
```
discovered_links|0
discovery_runs|3
documents|0
fetch_items|0
fetch_runs|0
ingest_jobs|2
seed_runs|1
source_registry|13
(8 rows)
--
discovery_runs.status.failed|3
ingest_jobs.status.completed|1
ingest_jobs.status.failed|1
(3 rows)
```
## Round 1 - After Ingest
```
discovered_links|0
discovery_runs|3
documents|0
fetch_items|0
fetch_runs|0
ingest_jobs|3
seed_runs|1
source_registry|13
(8 rows)
--
discovery_runs.status.failed|3
ingest_jobs.status.completed|2
ingest_jobs.status.failed|1
(3 rows)
```
## Round 2 - After Seed
```
discovered_links|0
discovery_runs|3
documents|0
fetch_items|0
fetch_runs|0
ingest_jobs|4
seed_runs|1
source_registry|13
(8 rows)
--
discovery_runs.status.failed|3
ingest_jobs.status.completed|2
ingest_jobs.status.failed|1
ingest_jobs.status.pending|1
(4 rows)
```
## Round 2 - After Discovery
```
discovered_links|0
discovery_runs|3
documents|0
fetch_items|0
fetch_runs|0
ingest_jobs|4
seed_runs|1
source_registry|13
(8 rows)
--
discovery_runs.status.failed|3
ingest_jobs.status.completed|2
ingest_jobs.status.failed|1
ingest_jobs.status.pending|1
(4 rows)
```
## Round 2 - After Fetch
```
discovered_links|0
discovery_runs|3
documents|0
fetch_items|0
fetch_runs|1
ingest_jobs|5
seed_runs|2
source_registry|13
(8 rows)
--
discovery_runs.status.failed|3
fetch_runs.status.completed|1
ingest_jobs.status.completed|4
ingest_jobs.status.failed|1
(4 rows)
```
## Round 2 - After Ingest
```
discovered_links|0
discovery_runs|3
documents|0
fetch_items|0
fetch_runs|1
ingest_jobs|5
seed_runs|2
source_registry|13
(8 rows)
--
discovery_runs.status.failed|3
fetch_runs.status.completed|1
ingest_jobs.status.completed|4
ingest_jobs.status.failed|1
(4 rows)
```
## API Raw Results
### Round 1
- seed trigger: `{"success":true,"job_id":"ec9adf5b-3f30-4f41-a564-df1775b710fd","message":"Seed job enqueued. Worker will load sources from YAML, persist with retry, and register in seed_runs. Poll GET /api/v1/dashboard/jobs or GET /api/v1/dashboard/seed/last for result."}`
- seed last: `{"id":"7370c86c-a8a1-4767-8723-6abcc7ef006e","job_id":"ec9adf5b-3f30-4f41-a564-df1775b710fd","completed_at":"2026-02-14T03:35:31.505796Z","sources_total":13,"sources_seeded":13,"sources_failed":0,"status":"completed","error_summary":null}`
- discovery trigger: `{"statusCode":500,"message":"An error occurred while processing your request","requestId":"0HNJBF8AP470N:00000001","detail":"Failed to read parameter \"RefreshSourceRequest request\" from the request body as JSON.","stackTrace":"   at Microsoft.AspNetCore.Http.RequestDelegateFactory.Log.InvalidJsonRequestBody(HttpContext httpContext, String parameterTypeName, String parameterName, Exception exception, Boolean shouldThrow)\n   at Microsoft.AspNetCore.Http.RequestDelegateFactory.<HandleRequestBodyAndCompileRequestDelegateForJson>g__TryReadBodyAsync|102_0(HttpContext httpContext, Type bodyType, String parameterTypeName, String parameterName, Boolean allowEmptyRequestBody, Boolean throwOnBadRequest, JsonTypeInfo jsonTypeInfo)\n   at Microsoft.AspNetCore.Http.RequestDelegateFactory.<>c__DisplayClass102_2.<<HandleRequestBodyAndCompileRequestDelegateForJson>b__2>d.MoveNext()\n--- End of stack trace from previous location ---\n   at Microsoft.AspNetCore.Routing.EndpointMiddleware.<Invoke>g__AwaitRequestTask|7_0(Endpoint endpoint, Task requestTask, ILogger logger)\n   at Swashbuckle.AspNetCore.SwaggerUI.SwaggerUIMiddleware.Invoke(HttpContext httpContext)\n   at Swashbuckle.AspNetCore.Swagger.SwaggerMiddleware.Invoke(HttpContext httpContext, ISwaggerProvider swaggerProvider)\n   at Microsoft.AspNetCore.Authorization.AuthorizationMiddleware.Invoke(HttpContext context)\n   at Microsoft.AspNetCore.Authentication.AuthenticationMiddleware.Invoke(HttpContext context)\n   at Program.<>c.<<<Main>$>b__0_6>d.MoveNext() in /home/fgamajr/dev/gabi-kimi/src/Gabi.Api/Program.cs:line 123\n--- End of stack trace from previous location ---\n   at Microsoft.AspNetCore.RateLimiting.RateLimitingMiddleware.InvokeInternal(HttpContext context, EnableRateLimitingAttribute enableRateLimitingAttribute)\n   at Gabi.Api.Middleware.SecurityHeadersMiddleware.InvokeAsync(HttpContext context) in /home/fgamajr/dev/gabi-kimi/src/Gabi.Api/Middleware/SecurityHeadersMiddleware.cs:line 29\n   at Gabi.Api.Middleware.ExceptionHandlingMiddleware.InvokeAsync(HttpContext context) in /home/fgamajr/dev/gabi-kimi/src/Gabi.Api/Middleware/ExceptionHandlingMiddleware.cs:line 28"}`
- discovery last: `{"id":"f34e5b25-7160-4efb-9d28-49699eabc029","job_id":"fa21d8ce-e936-48cf-901b-73a7fad28f66","source_id":"tcu_acordaos","completed_at":"2026-02-14T03:38:10.650056Z","links_total":0,"status":"failed","error_summary":"URL is required for StaticUrl mode (Parameter 'config')"}`
- fetch trigger: `{"success":true,"job_id":"fa21d8ce-e936-48cf-901b-73a7fad28f66","message":"Job already in progress for tcu_acordaos"}`
- fetch last: `{"status":"timeout"}`
- ingest trigger: `{"success":true,"job_id":"f2ccbe31-2e82-4208-90d1-23e8b7ed24fc","message":"ingest queued for tcu_acordaos"}`
- ingest completion: `{"status":"completed_or_timeout"}`
### Round 2
- seed trigger: `{"success":true,"job_id":"516488f6-1413-4612-b4a4-fa706d48ad17","message":"Seed job enqueued. Worker will load sources from YAML, persist with retry, and register in seed_runs. Poll GET /api/v1/dashboard/jobs or GET /api/v1/dashboard/seed/last for result."}`
- seed last: `{"id":"7370c86c-a8a1-4767-8723-6abcc7ef006e","job_id":"ec9adf5b-3f30-4f41-a564-df1775b710fd","completed_at":"2026-02-14T03:35:31.505796Z","sources_total":13,"sources_seeded":13,"sources_failed":0,"status":"completed","error_summary":null}`
- discovery trigger: `{"statusCode":500,"message":"An error occurred while processing your request","requestId":"0HNJBF8AP4760:00000001","detail":"Failed to read parameter \"RefreshSourceRequest request\" from the request body as JSON.","stackTrace":"   at Microsoft.AspNetCore.Http.RequestDelegateFactory.Log.InvalidJsonRequestBody(HttpContext httpContext, String parameterTypeName, String parameterName, Exception exception, Boolean shouldThrow)\n   at Microsoft.AspNetCore.Http.RequestDelegateFactory.<HandleRequestBodyAndCompileRequestDelegateForJson>g__TryReadBodyAsync|102_0(HttpContext httpContext, Type bodyType, String parameterTypeName, String parameterName, Boolean allowEmptyRequestBody, Boolean throwOnBadRequest, JsonTypeInfo jsonTypeInfo)\n   at Microsoft.AspNetCore.Http.RequestDelegateFactory.<>c__DisplayClass102_2.<<HandleRequestBodyAndCompileRequestDelegateForJson>b__2>d.MoveNext()\n--- End of stack trace from previous location ---\n   at Microsoft.AspNetCore.Routing.EndpointMiddleware.<Invoke>g__AwaitRequestTask|7_0(Endpoint endpoint, Task requestTask, ILogger logger)\n   at Swashbuckle.AspNetCore.SwaggerUI.SwaggerUIMiddleware.Invoke(HttpContext httpContext)\n   at Swashbuckle.AspNetCore.Swagger.SwaggerMiddleware.Invoke(HttpContext httpContext, ISwaggerProvider swaggerProvider)\n   at Microsoft.AspNetCore.Authorization.AuthorizationMiddleware.Invoke(HttpContext context)\n   at Microsoft.AspNetCore.Authentication.AuthenticationMiddleware.Invoke(HttpContext context)\n   at Program.<>c.<<<Main>$>b__0_6>d.MoveNext() in /home/fgamajr/dev/gabi-kimi/src/Gabi.Api/Program.cs:line 123\n--- End of stack trace from previous location ---\n   at Microsoft.AspNetCore.RateLimiting.RateLimitingMiddleware.InvokeInternal(HttpContext context, EnableRateLimitingAttribute enableRateLimitingAttribute)\n   at Gabi.Api.Middleware.SecurityHeadersMiddleware.InvokeAsync(HttpContext context) in /home/fgamajr/dev/gabi-kimi/src/Gabi.Api/Middleware/SecurityHeadersMiddleware.cs:line 29\n   at Gabi.Api.Middleware.ExceptionHandlingMiddleware.InvokeAsync(HttpContext context) in /home/fgamajr/dev/gabi-kimi/src/Gabi.Api/Middleware/ExceptionHandlingMiddleware.cs:line 28"}`
- discovery last: `{"id":"b8675db1-c945-46e3-bdbf-30be32a28036","job_id":"fa21d8ce-e936-48cf-901b-73a7fad28f66","source_id":"tcu_acordaos","completed_at":"2026-02-14T03:38:21.380586Z","links_total":0,"status":"failed","error_summary":"URL is required for StaticUrl mode (Parameter 'config')"}`
- fetch trigger: `{"success":true,"job_id":"164f3198-90a4-414c-bed3-c61c84175a59","message":"fetch queued for tcu_acordaos"}`
- fetch last: `{"id":"d3e993d1-3879-465e-8699-1d8c85606b0e","job_id":"164f3198-90a4-414c-bed3-c61c84175a59","source_id":"tcu_acordaos","completed_at":"2026-02-14T03:41:42.891524Z","items_total":0,"items_completed":0,"items_failed":0,"status":"completed","error_summary":null}`
- ingest trigger: `{"statusCode":500,"message":"An error occurred while processing your request","requestId":"0HNJBF8AP4767:00000001","detail":"An error occurred while saving the entity changes. See the inner exception for details.","stackTrace":"   at Microsoft.EntityFrameworkCore.Update.ReaderModificationCommandBatch.ExecuteAsync(IRelationalConnection connection, CancellationToken cancellationToken)\n   at Microsoft.EntityFrameworkCore.Update.Internal.BatchExecutor.ExecuteAsync(IEnumerable`1 commandBatches, IRelationalConnection connection, CancellationToken cancellationToken)\n   at Microsoft.EntityFrameworkCore.Update.Internal.BatchExecutor.ExecuteAsync(IEnumerable`1 commandBatches, IRelationalConnection connection, CancellationToken cancellationToken)\n   at Microsoft.EntityFrameworkCore.Update.Internal.BatchExecutor.ExecuteAsync(IEnumerable`1 commandBatches, IRelationalConnection connection, CancellationToken cancellationToken)\n   at Microsoft.EntityFrameworkCore.ChangeTracking.Internal.StateManager.SaveChangesAsync(IList`1 entriesToSave, CancellationToken cancellationToken)\n   at Microsoft.EntityFrameworkCore.ChangeTracking.Internal.StateManager.SaveChangesAsync(StateManager stateManager, Boolean acceptAllChangesOnSuccess, CancellationToken cancellationToken)\n   at Npgsql.EntityFrameworkCore.PostgreSQL.Storage.Internal.NpgsqlExecutionStrategy.ExecuteAsync[TState,TResult](TState state, Func`4 operation, Func`4 verifySucceeded, CancellationToken cancellationToken)\n   at Microsoft.EntityFrameworkCore.DbContext.SaveChangesAsync(Boolean acceptAllChangesOnSuccess, CancellationToken cancellationToken)\n   at Microsoft.EntityFrameworkCore.DbContext.SaveChangesAsync(Boolean acceptAllChangesOnSuccess, CancellationToken cancellationToken)\n   at Gabi.Postgres.Repositories.JobQueueRepository.EnqueueAsync(IngestJob job, CancellationToken ct) in /home/fgamajr/dev/gabi-kimi/src/Gabi.Postgres/Repositories/JobQueueRepository.cs:line 46\n   at Gabi.Api.Services.DashboardService.StartPhaseAsync(String sourceId, String phase, CancellationToken ct) in /home/fgamajr/dev/gabi-kimi/src/Gabi.Api/Services/DashboardService.cs:line 547\n   at Program.<>c.<<<Main>$>b__0_27>d.MoveNext() in /home/fgamajr/dev/gabi-kimi/src/Gabi.Api/Program.cs:line 376\n--- End of stack trace from previous location ---\n   at Microsoft.AspNetCore.Http.RequestDelegateFactory.ExecuteTaskResult[T](Task`1 task, HttpContext httpContext)\n   at Microsoft.AspNetCore.Routing.EndpointMiddleware.<Invoke>g__AwaitRequestTask|7_0(Endpoint endpoint, Task requestTask, ILogger logger)\n   at Swashbuckle.AspNetCore.SwaggerUI.SwaggerUIMiddleware.Invoke(HttpContext httpContext)\n   at Swashbuckle.AspNetCore.Swagger.SwaggerMiddleware.Invoke(HttpContext httpContext, ISwaggerProvider swaggerProvider)\n   at Microsoft.AspNetCore.Authorization.AuthorizationMiddleware.Invoke(HttpContext context)\n   at Microsoft.AspNetCore.Authentication.AuthenticationMiddleware.Invoke(HttpContext context)\n   at Program.<>c.<<<Main>$>b__0_6>d.MoveNext() in /home/fgamajr/dev/gabi-kimi/src/Gabi.Api/Program.cs:line 123\n--- End of stack trace from previous location ---\n   at Microsoft.AspNetCore.RateLimiting.RateLimitingMiddleware.InvokeInternal(HttpContext context, EnableRateLimitingAttribute enableRateLimitingAttribute)\n   at Gabi.Api.Middleware.SecurityHeadersMiddleware.InvokeAsync(HttpContext context) in /home/fgamajr/dev/gabi-kimi/src/Gabi.Api/Middleware/SecurityHeadersMiddleware.cs:line 29\n   at Gabi.Api.Middleware.ExceptionHandlingMiddleware.InvokeAsync(HttpContext context) in /home/fgamajr/dev/gabi-kimi/src/Gabi.Api/Middleware/ExceptionHandlingMiddleware.cs:line 28"}`
- ingest completion: `{"status":"completed_or_timeout"}`
## Round 3 - Fail-safe (Discovery Without Seed)
```
discovered_links|0
discovery_runs|0
documents|0
fetch_items|0
fetch_runs|0
ingest_jobs|0
seed_runs|0
source_registry|13
(8 rows)
```
- discovery trigger http: `404`
- discovery trigger body: `{"success":false,"job_id":null,"message":"Source not found: tcu_acordaos"}`
