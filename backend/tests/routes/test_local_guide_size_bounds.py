import json

import pytest

from app.services.reader_guide_service import observation_text, validate_result


def facts(count=20, references=3, description='Observed fact.'):
    citations = [{'chapter': 1, 'block_id': f'block-{i}', 'quote': str(i) + 'x' * 499} for i in range(8)]
    value = {'characters': [{'name': f'Person-{i}', 'description': description, 'appearance': None,
        'certainty': 'observed', 'citations': citations[:references]} for i in range(count)],
        'relationships': [], 'locations': [], 'glossary': [], 'recap': None, 'citations': citations}
    chunks = [[{'chapter': row['chapter'], 'block_id': row['block_id'], 'text': row['quote']} for row in citations]]
    return value, chunks


def test_local_repeated_citations_keep_every_fact_with_bounded_compact_observations():
    value, chunks = facts()
    assert 18000 < len(json.dumps(value).encode()) < 96000
    result, citations = validate_result(json.dumps(value), chunks, local=True)
    packed = observation_text(result, local=True)
    assert len(packed.encode()) <= 18000
    compact = json.loads(packed)
    assert len(compact['characters']) == len(result['characters']) == 20
    assert compact['citations'] == citations == value['citations']
    for before, after in zip(result['characters'], compact['characters']):
        assert before == {**after, 'citations': [compact['citations'][index] for index in after['citations']]}


def test_remote_inline_output_retains_existing_18kb_limit():
    value, chunks = facts()
    with pytest.raises(ValueError, match='oversized'):
        validate_result(json.dumps(value), chunks)


def test_local_compaction_never_bypasses_exact_citation_validation():
    value, chunks = facts()
    value['characters'][0]['citations'] = [{'chapter': 1, 'block_id': 'block-0', 'quote': 'Not in evidence'}]
    with pytest.raises(ValueError, match='unsupported nested citation'):
        validate_result(json.dumps(value), chunks, local=True)


def test_local_semantic_content_still_obeys_18kb_limit():
    value, chunks = facts(count=20, references=1, description='z' * 1000)
    assert len(json.dumps(value).encode()) < 96000
    with pytest.raises(ValueError, match='semantic content'):
        validate_result(json.dumps(value), chunks, local=True)


def test_local_expanded_output_has_independent_finite_limit():
    value, chunks = facts(count=30, references=8)
    assert len(json.dumps(value).encode()) > 96000
    with pytest.raises(ValueError, match='oversized'):
        validate_result(json.dumps(value), chunks, local=True)
