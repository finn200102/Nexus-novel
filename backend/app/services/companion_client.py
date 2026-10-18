"""Private bounded inference bridge; all billing remains in the novel backend."""
import json
import httpx
from config.settings import settings


def require_configured():
    if not settings.ANALYSIS_ENGINE_URL or not settings.ANALYSIS_ENGINE_API_KEY:
        raise ValueError("Configure the authenticated analysis service before using the companion")


def request(provider, *, prompt, system, max_tokens, api_key):
    require_configured()
    value = json.loads(prompt)
    body = {"question": value["question"], "through_chapter": value["through_chapter"],
            "evidence": [{key: row[key] for key in ("chapter", "block_id", "text")} for row in value["evidence"]],
            "provider": {"kind": provider.kind, "base_url": provider.base_url, "model": provider.model,
                         "api_key": api_key or None}, "max_tokens": max_tokens}
    with httpx.Client(timeout=httpx.Timeout(130, connect=5), trust_env=False, follow_redirects=False) as client:
        with client.stream("POST", settings.ANALYSIS_ENGINE_URL.rstrip("/") + "/v1/companion/questions", json=body,
                           headers={"X-Nexus-Analysis-Key": settings.ANALYSIS_ENGINE_API_KEY}) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes(64 * 1024):
                content.extend(chunk)
                if len(content) > 2_010_000:
                    raise ValueError("Companion service response exceeds its limit")
            result = json.loads(content)
            if result.get("pipeline_version") != "bounded-companion-v1":
                raise ValueError("Companion service interface is incompatible")
            return result["provider_response"]


def _guide_call(path, body, maximum):
    require_configured()
    with httpx.Client(timeout=httpx.Timeout(190, connect=5), trust_env=False, follow_redirects=False) as client:
        with client.stream('POST', settings.ANALYSIS_ENGINE_URL.rstrip('/') + '/v1/private-guide/' + path,
            json=body, headers={'X-Nexus-Analysis-Key': settings.ANALYSIS_ENGINE_API_KEY}) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes(64 * 1024):
                content.extend(chunk)
                if len(content) > maximum: raise ValueError('Private guide service response exceeds its limit')
            result = json.loads(content)
            if result.get('pipeline_version') != 'private-guide-v1': raise ValueError('Private guide interface is incompatible')
            return result['provider_response']


def guide_request(provider, *, prompt, system, max_tokens, api_key):
    value = json.loads(prompt)
    value = {key: value[key] for key in ('operation', 'through_chapter', 'evidence', 'observations') if key in value}
    return _guide_call('text', {**value,
        'provider': {'kind': provider.kind, 'base_url': provider.base_url, 'model': provider.model, 'api_key': api_key or None},
        'max_tokens': max_tokens}, 2_010_000)


def image_request(provider, *, prompt, system, image_size, image_quality, api_key):
    value = json.loads(prompt)
    value = {key: value[key] for key in ('through_chapter', 'evidence', 'observations', 'portrait_subject') if key in value}
    return _guide_call('portrait', {**value,
        'provider': {'kind': provider.kind, 'base_url': provider.base_url, 'model': provider.image_model, 'api_key': api_key or None},
        'image_size': image_size, 'image_quality': image_quality}, 11_210_000)
