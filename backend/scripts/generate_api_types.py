"""Deterministic, offline TypeScript contracts for explicitly covered API routes.

Run with the backend Python environment. This intentionally does not claim to
cover endpoints whose response models are still missing. Unsupported schemas
fail generation rather than silently weakening selected contracts to `any`.
"""
from __future__ import annotations
import argparse
import difflib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

BACKEND = Path(__file__).resolve().parents[1]
NOVEL = BACKEND.parent
DEFAULT_SCHEMA = BACKEND / 'contracts/reader.openapi.json'
DEFAULT_TYPES = NOVEL / 'frontend/src/generated/api.ts'
COVERED = {
    '/admin/source-manifest-reviews/novels/{novel_id}/head': ('get',),
    '/admin/source-manifest-reviews/novels/{novel_id}/context': ('get',),
    '/admin/source-manifest-reviews/preview': ('post',),
    '/admin/source-manifest-reviews': ('get',),
    '/admin/source-manifest-reviews/{review_id}': ('get',),
    '/admin/source-manifest-reviews/{review_id}/apply': ('post',),
    '/admin/source-manifest-reviews/{review_id}/undo': ('post',),
    '/kobo-devices/{device_id}/books': ('get',),
    '/kobo-devices/{device_id}/books/{entitlement}/confirm-version': ('post',),
    '/audio/stories/{novel_id}/recordings': ('get',),
    '/me/import-reading-reviews': ('get',),
    '/me/import-reading-reviews/{review_id}': ('get',),
    '/me/import-reading-reviews/{review_id}/chapters': ('get',),
    '/me/import-reading-reviews/{review_id}/preview': ('post',),
    '/me/import-reading-reviews/{review_id}/apply': ('post',),
    '/reader/glossary/{novel_id}': ('post',),
    '/reader/glossary/{novel_id}/entries': ('get',),
    '/chapter/novel/{novel_id}/manifest-state': ('get',),
    '/chapter/key/{novel_id}/{chapter_key}': ('get',),
    '/chapter/key/{novel_id}/{chapter_key}/content': ('get',),
    '/chapter/novel/{novel_id}/manifest/preview': ('post',),
    '/chapter/novel/{novel_id}/manifest/apply': ('post',),
    '/chapter/novel/{novel_id}/manifest/reviews': ('get',),
    '/chapter/novel/{novel_id}/manifest/reviews/{review_id}': ('get',),
    '/chapter/novel/{novel_id}/manifest/reviews/{review_id}/items': ('get',),
    '/chapter/novel/{novel_id}/manifest/reviews/{review_id}/remote': ('get',),
    '/chapter/novel/{novel_id}/manifest/reviews/{review_id}/undo': ('post',),
    '/audio/stories/{novel_id}': ('get',),
    '/audio/stories/{novel_id}/jobs': ('post',),
    '/audio/jobs': ('get', 'post'),
    '/audio/jobs/{job_id}': ('get', 'delete'),
    '/audio/jobs/{job_id}/retry': ('post',),
    '/audio/jobs/{job_id}/cancel': ('post',),
    '/audio/jobs/{job_id}/manifest': ('get',),
    '/reader/stories/{novel_id}/translations': ('get',),
    '/reader/stories/{novel_id}/translation-chapters': ('get',),
    '/reader/translations/{novel_id}/{chapter_number}': ('get', 'post'),
    '/reader/translation-jobs/{job_id}': ('post',),
    '/reader/stories/{novel_id}/guide': ('get',),
    '/reader/stories/{novel_id}/guide/preview': ('post',),
    '/reader/stories/{novel_id}/guide/jobs': ('post',),
    '/reader/stories/{novel_id}/guide/jobs/{job_id}': ('get',),
    '/reader/stories/{novel_id}/guide/jobs/{job_id}/cancel': ('post',),
    '/reader/stories/{novel_id}/guide/jobs/{job_id}/retry': ('post',),
    '/reader/stories/{novel_id}/guide/artifacts/{artifact_id}': ('get',),
    '/reader/providers': ('get','post'),
    '/reader/providers/{provider_id}': ('put',),
    '/reader/providers/{provider_id}/budget': ('put',),
    '/reader/permissions/{novel_id}/{provider_id}': ('get','put'),
    '/reader/permissions/{novel_id}/{provider_id}/portrait': ('patch',),
    '/catalog-scrapes/{definition_id}/active-jobs': ('get',),
    '/catalog-scrapes/capabilities': ('get',),
    '/catalog-scrapes/capabilities/{site}': ('get',),
    '/catalog-scrapes/preview': ('post',),
    '/catalog-scrapes': ('post', 'get'),
    '/catalog-scrapes/templates': ('get',),
    '/catalog-scrapes/{definition_id}': ('get', 'patch', 'delete'),
    '/catalog-scrapes/{definition_id}/pause': ('post',),
    '/catalog-scrapes/{definition_id}/resume': ('post',),
    '/catalog-scrapes/{definition_id}/run': ('post',),
    '/catalog-scrapes/jobs/{job_id}': ('get',),
    '/catalog-scrapes/jobs/{job_id}/candidates': ('get',),
    '/catalog-scrapes/jobs/{job_id}/retry': ('post',),
    '/catalog-scrapes/jobs/{job_id}/cancel': ('post',),
    '/catalog-scrapes/taxonomies/{site}/{taxonomy_type}': ('get',),
    '/catalog-scrapes/{definition_id}/rebind': ('post',),
    '/catalog-scrapes/jobs/{job_id}/candidates/{candidate_id}': ('patch',),

    '/discovery/live/capabilities': ('get',),
    '/discovery/live/local': ('get',),
    '/discovery/live/source': ('get',),
    '/discovery/live/browse': ('get',),
    '/discovery/works': ('get',),
    '/discovery/edition-groups/{novel_id}': ('get',),
    '/discovery/vocabulary/terms': ('get',),
    '/admin/review-catalog/lookup': ('get',),
    '/admin/vocabulary/terms': ('get', 'post'),
    '/admin/vocabulary/raw': ('get',),
    '/admin/vocabulary/story-scopes': ('get',),
    '/admin/vocabulary/aliases': ('get', 'post'),
    '/admin/vocabulary/aliases/{alias_id}': ('get',),
    '/admin/vocabulary/aliases/{alias_id}/preview': ('post',),
    '/admin/vocabulary/aliases/{alias_id}/decide': ('post',),
    '/admin/edition-group-reviews': ('get',),
    '/admin/edition-group-reviews/preview': ('post',),
    '/admin/edition-group-reviews/{review_id}': ('get',),
    '/admin/edition-group-reviews/{review_id}/apply': ('post',),
    '/admin/edition-group-reviews/{review_id}/undo': ('post',),
    '/catalog-watches/{search_id}': ('get',),
    '/catalog-watches/{search_id}/prepare': ('post',),
    '/catalog-watches/{search_id}/activate': ('post',),
    '/catalog-watches/{search_id}/pause': ('post',),
    '/catalog-watches/{search_id}/results': ('post',),
    '/catalog-watches/{search_id}/matches': ('get',),
    '/catalog-watches/{search_id}/matches/{match_id}/read': ('post',),
    '/library-views/preview': ('post',),
    '/library-views/options': ('get',),
    '/smart-shelves': ('get', 'post'),
    '/smart-shelves/{shelf_id}': ('put', 'delete'),
    '/smart-shelves/{shelf_id}/results': ('post',),
    '/saved-searches': ('get', 'post'),
    '/saved-searches/{search_id}': ('put', 'delete'),
    '/chapter/reading-summary/{novel_id}': ('get',),
    '/chapter/reading-chapters/{novel_id}': ('get',),
    '/stats/reading-time': ('post',), '/stats/summary': ('get',),
    '/stats/preferences': ('get', 'put'), '/stats/goals/{year}': ('get', 'put'),
    '/stats/review/{year}': ('get',),
    '/reading/stories/{novel_id}/runs': ('get',),
    '/reading/stories/{novel_id}/runs/start': ('post',),
    '/reading/stories/{novel_id}/runs/finish': ('post',),
    '/reading/stories/{novel_id}/runs/drop': ('post',),
    '/reading/journal': ('get',),
    '/reader/preferences': ('get', 'put'),
    '/reader/preferences/stories/{novel_id}': ('get', 'put'),
    '/reader/providers/{provider_id}/requests': ('get',),
    '/reader/providers/{provider_id}/requests/{request_key}/reconcile': ('post',),
    '/reader/stories/{novel_id}/offline-manifest': ('get',),
    '/reader/offline/translations/{job_id}': ('get',),
    '/reader/source-migrations/targets': ('get',),
    '/reader/source-migrations/chapters/{novel_id}': ('get',),
    '/reader/source-migrations/preview': ('post',),
    '/reader/source-migrations/apply': ('post',),
    '/reader/source-migrations': ('get',),
    '/reader/source-migrations/{migration_id}': ('get',),
    '/reader/source-migrations/{migration_id}/undo': ('post',),
    '/chapter/': ('post', 'put'),
    '/chapter/download/{library_id}/{novel_id}/{chapter_number}': ('get',),
    '/chapter/queue/{library_id}/{novel_id}': ('post',),
    '/chapter/queue/{novel_id}': ('get',),
    '/chapter/progress/{novel_id}': ('get', 'put'),
    '/chapter/progress/recent': ('get',),
    '/chapter/history/{novel_id}': ('get',),
    '/chapter/recap/{novel_id}': ('get',),
    '/chapter/annotations/{novel_id}': ('get', 'post'),
    '/chapter/annotations/{annotation_id}': ('delete',),
    '/chapter/{novel_id}': ('get',),
    '/chapter/{novel_id}/{chapter_number}': ('get',),
    '/chapter/navigation/{novel_id}/{chapter_number}': ('get',),
    '/chapter/versions/{novel_id}/{chapter_number}': ('get',),
    '/chapter/versions/{novel_id}/{chapter_number}/{content_version}': ('get',),
    '/chapter/content/library/{library_id}/{novel_id}/{chapter_number}': ('get',),
    '/chapter/{chapter_id}': ('delete',),
    '/chapter/{chapter_id}/status': ('patch',),
    '/chapter/novel/{novel_id}/download-status': ('get',),
    '/chapter/{chapter_id}/download': ('delete',),
    '/chapter/novel/{novel_id}/cancel-all-downloads': ('post',),
}
REF_PREFIX = '#/components/schemas/'


def export_openapi():
    # Isolated process and directory: never load a developer's .env, create
    # signing keys in their downloads, start a lifespan or contact a service.
    child = '''
import contextlib,json,socket,sqlite3,sys
import dotenv
from sqlalchemy.engine import Engine
# find_dotenv otherwise searches relative to imported module files, not cwd.
dotenv.load_dotenv=lambda *args,**kwargs:False
def prohibited(*args,**kwargs):raise RuntimeError("Contract export cannot use a database or network")
socket.socket.connect=prohibited
socket.socket.connect_ex=prohibited
socket.create_connection=prohibited
socket.getaddrinfo=prohibited
sqlite3.connect=prohibited
sqlite3.dbapi2.connect=prohibited
Engine.connect=prohibited
Engine.raw_connection=prohibited
sys.path.insert(0,sys.argv[1])
with contextlib.redirect_stdout(sys.stderr):
    from app.main import app
    value=app.openapi()
sys.stdout.write(json.dumps(value,sort_keys=True))
'''
    with tempfile.TemporaryDirectory(prefix='nexus-contract-export-') as directory:
        env = {
            'DATABASE_URL': 'sqlite:///:memory:', 'DOWNLOAD_PATH': directory,
            'SECRET_KEY': 'nexus-contract-export-only-signing-key',
            'VAPID_PRIVATE_KEY': 'contract-export-only', 'VAPID_PUBLIC_KEY': 'contract-export-only',
            'RUN_MIGRATIONS_ON_STARTUP': 'false', 'PYTHONDONTWRITEBYTECODE': '1',
        }
        result = subprocess.run([sys.executable, '-B', '-c', child, str(BACKEND)], cwd=directory,
                                env=env, text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise ValueError('Offline OpenAPI export failed: ' + result.stderr[-3000:])
        return json.loads(result.stdout)


def references(value):
    if isinstance(value, dict):
        if '$ref' in value:
            ref = value['$ref']
            if not ref.startswith(REF_PREFIX): raise ValueError(f'Unsupported schema reference: {ref}')
            yield ref[len(REF_PREFIX):]
        for item in value.values(): yield from references(item)
    elif isinstance(value, list):
        for item in value: yield from references(item)


def select_contract(document):
    paths = {}
    for path, methods in sorted(COVERED.items()):
        actual = document.get('paths', {}).get(path, {})
        paths[path] = {}
        for method in methods:
            if method not in actual: raise ValueError(f'Missing covered endpoint: {method.upper()} {path}')
            operation = actual[method]
            success = {status: response for status, response in operation.get('responses', {}).items() if status.startswith('2')}
            if not success: raise ValueError(f'Missing success response: {method.upper()} {path}')
            for status, response in success.items():
                if status in ('204', '205'):
                    if response.get('content'): raise ValueError('No-content response cannot declare a body')
                    continue
                schema = response.get('content', {}).get('application/json', {}).get('schema')
                if not schema or schema == {'type': 'object'}: raise ValueError(f'Untyped response: {method.upper()} {path}')
            for status, response in operation.get('responses', {}).items():
                if status.startswith('2'): continue
                content = response.get('content', {})
                if 'application/json' in content:
                    schema = content['application/json'].get('schema')
                    if not schema or schema == {'type': 'object'}:
                        raise ValueError(f'Untyped error response: {method.upper()} {path} {status}')
            paths[path][method] = operation
    schemas = document.get('components', {}).get('schemas', {})
    selected, pending = {}, list(references(paths))
    while pending:
        name = pending.pop()
        if name in selected: continue
        if name not in schemas: raise ValueError(f'Missing component: {name}')
        if not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*', name): raise ValueError(f'Invalid TypeScript component name: {name}')
        selected[name] = schemas[name]
        pending.extend(references(schemas[name]))
    components = {'schemas': dict(sorted(selected.items()))}
    security_names = {name for methods in paths.values() for operation in methods.values()
                      for requirement in operation.get('security', []) for name in requirement}
    if security_names:
        schemes = document.get('components', {}).get('securitySchemes', {})
        if security_names - schemes.keys(): raise ValueError('Missing referenced security scheme')
        components['securitySchemes'] = {name: schemes[name] for name in sorted(security_names)}
    return {'openapi': document['openapi'], 'info': document['info'], 'paths': paths, 'components': components}


def literal(value):
    if isinstance(value, (dict, list)): raise ValueError('Object and array literals are not supported')
    return json.dumps(value, ensure_ascii=True)


def schema_type(schema):
    if schema is True: return 'unknown'
    if schema is False: return 'never'
    if not isinstance(schema, dict) or not schema: raise ValueError('Untyped schema is not supported')
    if schema.get('nullable'):
        return '(' + schema_type({key: value for key, value in schema.items() if key != 'nullable'}) + ' | null)'
    unsupported = {'not', 'if', 'then', 'else', 'patternProperties', 'unevaluatedProperties', 'contains'} & schema.keys()
    if unsupported: raise ValueError('Unsupported schema keywords: ' + ', '.join(sorted(unsupported)))
    if len({'$ref', 'const', 'enum', 'anyOf', 'oneOf', 'allOf'} & schema.keys()) > 1:
        raise ValueError('Combined schema composition requires explicit generator support')
    if '$ref' in schema:
        ref = schema['$ref']
        if not ref.startswith(REF_PREFIX): raise ValueError(f'Unsupported schema reference: {ref}')
        if {'properties', 'anyOf', 'oneOf', 'allOf', 'type', 'enum', 'const'} & schema.keys():
            raise ValueError('Structural siblings of $ref require explicit generator support')
        return ref[len(REF_PREFIX):]
    if 'const' in schema: return literal(schema['const'])
    if 'enum' in schema: return ' | '.join(literal(item) for item in schema['enum']) or 'never'
    for keyword, separator in [('anyOf', ' | '), ('oneOf', ' | '), ('allOf', ' & ')]:
        if keyword in schema:
            if not schema[keyword]: raise ValueError('Empty schema composition is not supported')
            if {'properties', 'type', 'additionalProperties'} & schema.keys():
                raise ValueError('Structural siblings of schema composition require explicit generator support')
            return '(' + separator.join(schema_type(item) for item in schema[keyword]) + ')'
    kind = schema.get('type')
    if isinstance(kind, list): return '(' + ' | '.join(schema_type({**schema, 'type': item}) for item in kind) + ')'
    if kind == 'null': return 'null'
    if kind in ('integer', 'number'): return 'number'
    if kind == 'string': return 'string'
    if kind == 'boolean': return 'boolean'
    if kind == 'array':
        if 'prefixItems' in schema: raise ValueError('Tuple schemas require explicit generator support')
        if 'items' not in schema: raise ValueError('Untyped array items are not supported')
        return 'Array<' + schema_type(schema['items']) + '>'
    if kind == 'object' or 'properties' in schema or 'additionalProperties' in schema:
        required = set(schema.get('required', []))
        properties = schema.get('properties', {})
        if 'propertyNames' in schema:
            names = schema['propertyNames']
            values = names.get('enum') if isinstance(names, dict) else None
            if (properties or required or not isinstance(names, dict)
                    or set(names) - {'enum', 'type', 'title', 'description'}
                    or names.get('type', 'string') != 'string'
                    or not isinstance(values, list) or not values
                    or any(not isinstance(value, str) for value in values)
                    or 'additionalProperties' not in schema):
                raise ValueError('Unsupported propertyNames dictionary schema')
            # propertyNames constrains allowed keys without requiring them.
            # Record alone would incorrectly promise every enum key exists.
            extra = schema['additionalProperties']
            value_type = 'unknown' if extra is True else 'never' if extra is False else schema_type(extra)
            return 'Partial<Record<' + ' | '.join(literal(value) for value in values) + ', ' + value_type + '>>'
        if not properties and 'additionalProperties' not in schema:
            raise ValueError('Untyped object is not supported')
        fields = [f'{json.dumps(key)}{"" if key in required else "?"}: {schema_type(value)};' for key, value in sorted(properties.items())]
        extra = schema.get('additionalProperties', False)
        if not isinstance(extra, (bool, dict)): raise ValueError('Invalid additionalProperties schema')
        if extra is True: fields.append('[key: string]: unknown;')
        elif isinstance(extra, dict): fields.append('[key: string]: ' + schema_type(extra) + ';')
        return '{ ' + ' '.join(fields) + ' }' if fields else 'Record<string, never>'
    raise ValueError(f'Unsupported or untyped schema: {schema}')


def generate_types(document):
    lines = ['// Generated by backend/scripts/generate_api_types.py. Do not edit.',
             '// Coverage is explicit in ApiOperations; other API routes remain outside this contract.',
             '// errors includes only explicitly documented JSON errors; other failures remain unknown.', '']
    for name, schema in sorted(document['components']['schemas'].items()):
        lines.append(f'export type {name} = {schema_type(schema)};')
    lines.extend(['', 'export interface ApiOperations {'])
    for path, methods in sorted(document['paths'].items()):
        for method, operation in sorted(methods.items()):
            request = operation.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema')
            responses = ['void' if status in ('204', '205') else schema_type(response['content']['application/json']['schema'])
                         for status, response in sorted(operation['responses'].items()) if status.startswith('2')]
            errors = [f'{json.dumps(status)}: {schema_type(response["content"]["application/json"]["schema"])};'
                      for status, response in sorted(operation['responses'].items())
                      if not status.startswith('2') and 'application/json' in response.get('content', {})]
            error_map = '{ ' + ' '.join(errors) + ' }' if errors else 'Record<string, never>'
            parameters = {}
            for location in ('path', 'query'):
                values = operation.get('parameters', [])
                fields = [f'{json.dumps(value["name"])}{"" if value.get("required") else "?"}: {schema_type(value["schema"])};'
                          for value in values if value['in'] == location]
                parameters[location] = '{ ' + ' '.join(fields) + ' }' if fields else 'Record<string, never>'
            lines.append(f'  {json.dumps(method.upper()+" "+path)}: {{ request: {schema_type(request) if request else "never"}; response: {" | ".join(responses)}; errors: {error_map}; path: {parameters["path"]}; query: {parameters["query"]}; }};')
    lines.extend(['}', ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail if committed contracts are stale; writes nothing')
    parser.add_argument('--schema-output', type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument('--types-output', type=Path, default=DEFAULT_TYPES)
    args = parser.parse_args()
    document = select_contract(export_openapi())
    outputs = [(args.schema_output, json.dumps(document, indent=2, sort_keys=True) + '\n'),
               (args.types_output, generate_types(document))]
    stale = []
    for path, value in outputs:
        existing = path.read_text() if path.exists() else ''
        if existing == value: continue
        if args.check:
            stale.append(str(path))
            sys.stderr.writelines(list(difflib.unified_diff(existing.splitlines(True), value.splitlines(True), fromfile=str(path), tofile='generated'))[:100])
        else:
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)
    if stale: raise SystemExit('Stale API contracts: ' + ', '.join(stale))
    print(f'{len(document["paths"])} paths / {sum(len(methods) for methods in document["paths"].values())} operations checked' if args.check else 'API contracts generated')


if __name__ == '__main__': main()
