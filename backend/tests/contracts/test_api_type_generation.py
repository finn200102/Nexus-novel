"""Contract freshness, conservative schema support, and isolated introspection."""
import importlib.util
import json
from pathlib import Path
import sys
import pytest

SCRIPT=Path(__file__).resolve().parents[2]/'scripts/generate_api_types.py'
spec=importlib.util.spec_from_file_location('api_type_generator',SCRIPT)
generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)


def document():
    return {'openapi':'3.1.0','info':{'title':'Contract test','version':'1'},
        'paths':{'/test':{'get':{'security':[{'Session':[]}], 'responses':{'200':{'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Example'}}}}}}}},
        'components':{'securitySchemes':{'Session':{'type':'http','scheme':'bearer'}},
            'schemas':{'Example':{'type':'object','required':['id'],'properties':{'id':{'type':'integer'},'label':{'anyOf':[{'type':'string'},{'type':'null'}]}}},
                       'Unused':{'type':'string'}}}}


def test_selection_keeps_references_and_security_but_excludes_uncovered_routes(monkeypatch):
    monkeypatch.setattr(generator,'COVERED',{'/test':('get',)})
    value=generator.select_contract(document())
    assert set(value['components']['schemas'])=={'Example'}
    assert value['components']['securitySchemes']['Session']['scheme']=='bearer'
    generated=generator.generate_types(value)
    assert '"id": number' in generated and '"label"?: (string | null)' in generated
    assert '"GET /test"' in generated and 'request: never' in generated
    assert 'any;' not in generated


def test_missing_or_untyped_selected_response_fails_instead_of_claiming_coverage(monkeypatch):
    monkeypatch.setattr(generator,'COVERED',{'/missing':('get',)})
    with pytest.raises(ValueError,match='Missing covered endpoint'):generator.select_contract(document())
    monkeypatch.setattr(generator,'COVERED',{'/test':('get',)})
    value=document();value['paths']['/test']['get']['responses']['200']['content']['application/json']['schema']={}
    with pytest.raises(ValueError,match='Untyped response'):generator.select_contract(value)
    value=document();value['components']['schemas'].pop('Example')
    with pytest.raises(ValueError,match='Missing component'):generator.select_contract(value)


def test_declared_no_content_success_generates_void_and_rejects_accidental_body(monkeypatch):
    monkeypatch.setattr(generator,'COVERED',{'/test':('get',)})
    value=document();value['paths']['/test']['get']['responses']={'204':{'description':'Deleted'}}
    selected=generator.select_contract(value)
    assert 'response: void;' in generator.generate_types(selected)
    value['paths']['/test']['get']['responses']['204']['content']={'application/json':{'schema':{'type':'string'}}}
    with pytest.raises(ValueError,match='No-content response'):generator.select_contract(value)


def test_explicit_json_errors_are_typed_by_status_without_claiming_undocumented_errors(monkeypatch):
    monkeypatch.setattr(generator,'COVERED',{'/test':('get',)})
    value=document()
    value['components']['schemas']['Conflict']={'type':'object','required':['detail'],
        'properties':{'detail':{'type':'string'}}}
    value['paths']['/test']['get']['responses'].update({
        '409':{'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Conflict'}}}},
        '503':{'description':'Service unavailable; no response schema documented'},
    })
    selected=generator.select_contract(value)
    generated=generator.generate_types(selected)
    assert 'errors: { "409": Conflict; }' in generated
    assert '"503":' not in generated and 'export type Conflict' in generated
    value['paths']['/test']['get']['responses']['409']['content']['application/json']['schema']={}
    with pytest.raises(ValueError,match='Untyped error response'):generator.select_contract(value)


def test_operations_without_documented_json_errors_have_an_empty_error_map(monkeypatch):
    monkeypatch.setattr(generator,'COVERED',{'/test':('get',)})
    assert 'errors: Record<string, never>;' in generator.generate_types(generator.select_contract(document()))


@pytest.mark.parametrize('schema',[{}, {'type':'object'}, {'type':'array'}, {'type':'file'},
    {'type':'object','patternProperties':{'x':{'type':'string'}}}, {'allOf':[]},
    {'anyOf':[{'type':'string'}],'enum':['x']},
    {'$ref':'#/components/schemas/X','type':'string'},
    {'allOf':[{'type':'string'}],'properties':{'x':{'type':'number'}}}])
def test_unsupported_schemas_fail_closed(schema):
    with pytest.raises(ValueError):generator.schema_type(schema)


def test_structured_json_and_nullable_arrays_are_represented_without_any():
    assert generator.schema_type({'type':'object','additionalProperties':True})=='{ [key: string]: unknown; }'
    assert generator.schema_type({'type':'object','additionalProperties':{'type':'number'}})=='{ [key: string]: number; }'
    assert generator.schema_type({'type':'array','items':{'type':'string'},'nullable':True})=='(Array<string> | null)'
    assert generator.schema_type({'type':['number','null']})=='(number | null)'
    assert generator.schema_type({'type':'object','additionalProperties':False})=='Record<string, never>'


def test_check_mode_detects_stale_files_without_writing_them(tmp_path,monkeypatch):
    monkeypatch.setattr(generator,'COVERED',{'/test':('get',)})
    monkeypatch.setattr(generator,'export_openapi',document)
    schema=tmp_path/'schema.json';types=tmp_path/'types.ts'
    args=[str(SCRIPT),'--schema-output',str(schema),'--types-output',str(types)]
    monkeypatch.setattr(sys,'argv',args);generator.main()
    expected=(schema.read_bytes(),types.read_bytes())
    monkeypatch.setattr(sys,'argv',args+['--check']);generator.main()
    assert expected==(schema.read_bytes(),types.read_bytes())
    types.write_text('stale\n')
    with pytest.raises(SystemExit,match='Stale API contracts'):generator.main()
    assert types.read_text()=='stale\n' and schema.read_bytes()==expected[0]


def test_enum_dictionary_keys_are_optional_and_unknown_constraints_fail_closed():
    schema = {'type':'object', 'propertyNames':{'enum':['reading','completed']}, 'additionalProperties':{'type':'integer'}}
    assert generator.schema_type(schema) == 'Partial<Record<"reading" | "completed", number>>'
    for invalid in ({'pattern':'^reading$'}, {'enum':[1]}, {'enum':['reading'],'maxLength':7}):
        with pytest.raises(ValueError, match='propertyNames'):
            generator.schema_type({**schema, 'propertyNames':invalid})
    with pytest.raises(ValueError, match='propertyNames'):
        generator.schema_type({**schema, 'properties':{'reading':{'type':'integer'}}})


def test_real_export_is_deterministic_ignores_ambient_secrets_and_matches_generated_files(tmp_path,monkeypatch):
    sentinel='PRIVATE_CONTRACT_TEST_MUST_NOT_APPEAR'
    monkeypatch.setenv('SECRET_KEY',sentinel)
    monkeypatch.setenv('ANALYSIS_ENGINE_API_KEY',sentinel)
    monkeypatch.setenv('DATABASE_URL','postgresql://private.invalid/never-connect')
    forbidden=tmp_path/'never-created';monkeypatch.setenv('DOWNLOAD_PATH',str(forbidden))
    first=generator.select_contract(generator.export_openapi())
    second=generator.select_contract(generator.export_openapi())
    assert first==second and sentinel not in json.dumps(first)
    assert not forbidden.exists()
    assert generator.DEFAULT_SCHEMA.read_text()==json.dumps(first,indent=2,sort_keys=True)+'\n'
    assert generator.DEFAULT_TYPES.read_text()==generator.generate_types(first)
    assert sum(len(methods) for methods in first['paths'].values())==168
    for path in ('/chapter/novel/{novel_id}/manifest/preview', '/chapter/novel/{novel_id}/manifest/apply',
                 '/chapter/novel/{novel_id}/manifest/reviews/{review_id}/undo',
                 '/chapter/key/{novel_id}/{chapter_key}/content', '/audio/jobs/{job_id}/manifest'):
        assert path in first['paths']
    for model in ('TranslateInput', 'AudioJobCreate'):
        assert {'expected_chapter_key', 'expected_manifest_epoch', 'expected_manifest_revision',
                'expected_content_version'} <= first['components']['schemas'][model]['properties'].keys()
    assert {'chapter_key', 'manifest_epoch', 'manifest_revision'} <= set(first['components']['schemas']['OfflineManifestChapter']['required'])
    assert {'manifest_epoch', 'manifest_revision'} <= set(first['components']['schemas']['OfflineManifestPage']['required'])
    guide=first['paths']['/reader/stories/{novel_id}/guide']
    assert guide['get']['responses']['200']['content']['application/json']['schema']=={'$ref':'#/components/schemas/GuideState'}
    assert first['paths']['/reader/stories/{novel_id}/guide/jobs/{job_id}/retry']['post']['requestBody']['content']['application/json']['schema']=={'$ref':'#/components/schemas/GuideRetry'}
    assert first['paths']['/reader/providers']['get']['responses']['200']['content']['application/json']['schema']['items']=={'$ref':'#/components/schemas/ReaderProviderResponse'}
    assert first['paths']['/reader/permissions/{novel_id}/{provider_id}/portrait']['patch']['responses']['200']['content']['application/json']['schema']=={'$ref':'#/components/schemas/StoryPermissionResponse'}
    assert 'retry_input' in first['components']['schemas']['GuideJob']['properties']
    assert 'reuse_job_id' in first['components']['schemas']['GuidePreview']['properties']
    assert 'guide_portrait' in first['components']['schemas']['ProviderInput']['properties']['capabilities']['anyOf'][0]['items']['enum']
    assert '/discovery/works' in first['paths']
    assert first['paths']['/catalog-scrapes/{definition_id}/rebind']['post']['responses']['200']['content']['application/json']['schema']=={'$ref':'#/components/schemas/CatalogDefinitionResponse'}
    assert first['components']['schemas']['CatalogCapabilityResponse']['properties']['pagination_by_mode']
    assert 'created_by' not in first['components']['schemas']['CreateCatalogRequest']['properties']
    for endpoint in ('capabilities', 'local', 'source', 'browse'):
        assert '/discovery/live/' + endpoint in first['paths']
    assert '/admin/vocabulary/aliases/{alias_id}/decide' in first['paths']
    operation=first['paths']['/reader/providers/{provider_id}/requests/{request_key}/reconcile']['post']
    assert operation['responses']['409']['content']['application/json']['schema']=={'$ref':'#/components/schemas/ReaderProviderUsageConflictResponse'}
    assert '"409": ReaderProviderUsageConflictResponse' in generator.generate_types(first)


@pytest.mark.parametrize('operation',["import sqlite3; sqlite3.connect('unexpected.db')", "from sqlalchemy import create_engine; create_engine('sqlite:///unexpected.db').connect()", "import socket; socket.create_connection(('127.0.0.1',8180))"])
def test_introspection_prohibits_database_and_network_access(tmp_path,monkeypatch,operation):
    package=tmp_path/'app';package.mkdir();(package/'__init__.py').write_text('')
    (package/'main.py').write_text(operation)
    monkeypatch.setattr(generator,'BACKEND',tmp_path)
    with pytest.raises(ValueError,match='cannot use a database or network'):generator.export_openapi()
    assert not (tmp_path/'unexpected.db').exists()
