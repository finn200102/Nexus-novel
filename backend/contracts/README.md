# Generated reader API contracts

The checked-in `reader.openapi.json` and frontend `src/generated/api.ts` are
produced from FastAPI's actual response/request models, with an explicit set of
covered routes in `scripts/generate_api_types.py`. Current coverage is **43
operations**: statistics/time, measurement preferences, yearly goals/reviews,
reading runs/actions/journal, global/per-story reader preferences, chapter
metadata/content, downloads/queue/status/cancellation, reading progress/history/
recap, annotations, saved chapter versions and paid-provider request accounting/
reconciliation (including its structured conflict response), plus private offline
manifests and exact completed translation copies. Annotation deletion explicitly
has a bodyless 204 response represented as TypeScript void. Binary EPUB export
and other interfaces still need contracts and are not claimed as covered.
The operation map exposes successful responses and an `errors` map keyed by
status for explicitly documented JSON errors. An undocumented error (including
a response with only a description) remains unknown; generation does not claim
that such a response is bodyless or safe to interpret. Declared JSON errors
must have a supported schema. Existing conflict/permission endpoints still
need explicit response models before their error handling can be generated.

From `nexus-novel/backend`, using its installed environment:

```sh
uv run --locked python scripts/generate_api_types.py
uv run --locked python scripts/generate_api_types.py --check
```

Frontend maintainers can use `npm run generate:api` and `npm run check:api` when
`uv` is available. Neither command installs an extra JavaScript generator.
The backend CI job runs `--check` and fails when committed files are stale.
The check writes no output files. Regenerate after changing a covered contract;
do not hand-edit generated types or snapshots.

Introspection runs in a temporary working directory and a subprocess with a
minimal environment. It disables dotenv discovery, database connections,
network access and bytecode writes, and does not start the application lifespan.
It supplies export-only settings instead of reading installation keys or paid
provider credentials. No running Nexus instance is needed.

Only referenced schemas/security definitions enter the snapshot. Unsupported
schema constructs and untyped covered responses stop generation. Intentional
JSON extension maps remain `unknown`, while named fields stay typed; the
emitter never falls back to TypeScript `any`. Runtime constraints such as
maximum lengths and numeric bounds remain authoritative on the server and in
the OpenAPI snapshot. TypeScript does not replace runtime validation.

To extend coverage, add response models that preserve the existing JSON,
register the route in `COVERED`, add compatibility/introspection tests, regenerate,
and update its frontend service aliases. Extend the emitter with regression
coverage when a newly encountered schema construct cannot be represented yet.
Keep domain models such as locally adjustable typography separate from wire
response types where their supported ranges differ.
