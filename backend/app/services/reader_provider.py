"""Explicit provider routing, encrypted keys and conservative budget reservations."""
from decimal import Decimal, ROUND_CEILING
import os
from urllib.parse import urlsplit
import httpx
from app.services.notification_crypto import decrypt_url
from app.services.outbound_url import public_http_transport

MAX_OUTPUT_TOKENS = 4096


def validate_destination(kind, url):
    parts = urlsplit(url)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Provider URLs cannot contain credentials, queries or fragments")
    if kind in {"local", "local_translation"}:
        configured = {item.strip().rstrip("/") for item in os.getenv("NEXUS_LOCAL_AI_BASE_URLS", "").split(",") if item.strip()}
        single = os.getenv("NEXUS_LOCAL_AI_BASE_URL", "").rstrip("/")
        if single:
            configured.add(single)
        if not configured or url.rstrip("/") not in configured:
            raise ValueError("Ask the administrator to configure NEXUS_LOCAL_AI_BASE_URL for local processing")
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("Invalid local provider URL")
    elif parts.scheme != "https" or not parts.hostname:
        raise ValueError("Remote providers require an HTTPS URL")


def cost(provider, input_tokens, output_tokens):
    # USD per million tokens multiplied by token count equals micro-USD.
    return int((Decimal(provider.input_price) * input_tokens + Decimal(provider.output_price) * output_tokens).to_integral_value(rounding=ROUND_CEILING))


def invoke(db, provider, *, prompt, system, max_tokens=MAX_OUTPUT_TOKENS, request=None,
           translation_job_id=None, translation_block_index=None, retry_generation=None, purpose=None, job_key=None, item_key=None, authorize=None):
    from types import SimpleNamespace
    from app.services import reader_provider_usage as ledger
    approved_snapshot = ledger.snapshot(provider)
    db.refresh(provider)
    if approved_snapshot != ledger.snapshot(provider):
        raise ValueError("Provider configuration changed; review processing permission and pricing before trying again")
    if purpose is not None:
        if authorize is None:
            raise PermissionError('Private guide processing requires a fresh ownership and permission check')
        from app.schemas.translation import capabilities
        if purpose not in {'guide_extract', 'guide_synthesize'} or 'guide_text' not in capabilities(provider):
            raise ValueError('This provider is not explicitly configured for private guide text')
    if not provider.enabled:
        raise ValueError("This provider is disabled")
    validate_destination(provider.kind, provider.base_url)
    # This object is detached from mutable ORM settings throughout dispatch and
    # settlement. Only its public model/pricing fields enter the ledger.
    selected = SimpleNamespace(**ledger.snapshot(provider), id=provider.id, user_id=provider.user_id)
    selected.input_price, selected.output_price = Decimal(selected.input_price), Decimal(selected.output_price)
    local = selected.kind in {"local", "local_translation"}
    estimate_input = len((system + prompt).encode()) + 2048
    reserved = 0 if local else cost(selected, estimate_input, max_tokens)
    key = decrypt_url(provider.secret_ciphertext) if provider.secret_ciphertext else ""
    record = None
    if not local:
        if not key:
            raise ValueError("This remote provider has no API key")
        if not reserved or not provider.budget_microusd:
            raise ValueError("Set provider prices and a spending budget before paid processing")
    if not local or purpose is not None:
        record = ledger.reserve_request(db, provider, reserved, expected_snapshot=ledger.snapshot(selected),
            translation_job_id=translation_job_id, translation_block_index=translation_block_index, retry_generation=retry_generation,
            purpose=purpose, job_key=job_key, item_key=item_key, authorize=authorize)
    elif authorize is not None:
        authorize()
    record_key = record.request_key if record is not None else None
    db.rollback()  # No user/provider/job locks survive external provider I/O.
    try:
        answer = (request or direct_request)(selected, prompt=prompt, system=system, max_tokens=max_tokens, api_key=key)
        if selected.kind == "anthropic":
            text = "".join(item.get("text", "") for item in answer.get("content", []) if item.get("type") == "text")
            usage = answer.get("usage", {})
            input_tokens, output_tokens = usage.get("input_tokens", estimate_input if local else None), usage.get("output_tokens", max_tokens if local else None)
            complete = answer.get("stop_reason") != "max_tokens"
        else:
            choice = answer["choices"][0]
            text = choice["message"]["content"]
            usage = answer.get("usage", {})
            input_tokens, output_tokens = usage.get("prompt_tokens", estimate_input if local else None), usage.get("completion_tokens", max_tokens if local else None)
            complete = choice.get("finish_reason") != "length"
        if not local and any(type(value) is not int or not 0 <= value <= 10_000_000 for value in (input_tokens, output_tokens)):
            raise ValueError("Provider returned missing or invalid usage information")
        input_tokens, output_tokens = max(0, int(input_tokens)), max(0, int(output_tokens))
        if max(input_tokens, output_tokens) > 10_000_000:
            raise ValueError("Provider returned invalid usage information")
        charged = 0 if local else cost(selected, input_tokens, output_tokens)
    except Exception as exc:
        if record is not None:
            ledger.mark_unknown(db, record_key)
            raise ledger.ProviderRequestUnresolved("The paid provider response is unknown. Its reservation is retained; review the request ledger before explicitly retrying.") from exc
        raise
    if record is not None:
        ledger.settle_request(db, record_key, charged=charged, input_tokens=input_tokens, output_tokens=output_tokens)
    if not complete or not isinstance(text, str) or not text.strip() or len(text) > 100_000:
        raise ValueError("Provider returned empty, oversized or truncated text; the original is preserved")
    return text.strip(), input_tokens, output_tokens, charged


def direct_request(provider, *, prompt, system, max_tokens, api_key):
    headers = {"Content-Type": "application/json"}
    if provider.kind == "anthropic":
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        endpoint = provider.base_url.rstrip("/") + "/messages"
        payload = {"model": provider.model, "max_tokens": max_tokens, "system": system,
                   "messages": [{"role": "user", "content": prompt}]}
    else:
        if api_key:
            headers["Authorization"] = "Bearer " + api_key
        endpoint = provider.base_url.rstrip("/") + "/chat/completions"
        payload = {"model": provider.model, "max_tokens": max_tokens, "temperature": 0.1,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    transport = httpx.HTTPTransport() if provider.kind in {"local", "local_translation"} else public_http_transport(force_public=True)
    import json
    with httpx.Client(transport=transport, timeout=httpx.Timeout(120, connect=8), follow_redirects=False, trust_env=False) as client:
        with client.stream("POST", endpoint, json=payload, headers=headers) as response:
            if response.status_code >= 300:
                raise ValueError(f"Provider rejected the request (HTTP {response.status_code})")
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 2_000_000:
                    raise ValueError("Provider response exceeds the size limit")
            answer = json.loads(content)
    return answer


def invoke_image(db, provider, *, prompt, system='', purpose='guide_portrait', job_key=None,
                 item_key=None, retry_generation=None, image_size='1024x1024', image_quality='medium',
                 authorize=None, request=None):
    from types import SimpleNamespace
    from app.schemas.translation import capabilities, validate_image_configuration
    from app.services import reader_provider_usage as ledger
    from app.services.private_raster import decode_png
    if authorize is None:
        raise PermissionError('Private portraits require a fresh ownership and separate permission check')
    approved = ledger.snapshot(provider)
    db.refresh(provider)
    if approved != ledger.snapshot(provider) or not provider.enabled:
        raise ValueError('Provider configuration changed or is disabled')
    if purpose != 'guide_portrait' or 'guide_portrait' not in capabilities(provider):
        raise ValueError('Explicit portrait capability is required')
    validate_image_configuration(provider.kind, approved)
    if image_size not in provider.image_sizes or image_quality not in provider.image_qualities:
        raise ValueError('This image size or quality is not explicitly allowed')
    if not isinstance(prompt, str) or not prompt.strip() or len((system + prompt).encode()) > 16000:
        raise ValueError('Portrait prompt exceeds its bounded scope')
    validate_destination(provider.kind, provider.base_url)
    selected = SimpleNamespace(**approved, id=provider.id, user_id=provider.user_id)
    local = provider.kind == 'local'
    reserved = 0 if local else provider.image_price_microusd
    key = decrypt_url(provider.secret_ciphertext) if provider.secret_ciphertext else ''
    if not local and (not key or reserved <= 0 or not provider.budget_microusd):
        raise ValueError('Set an image price ceiling, API key and budget before paid portraits')
    row = ledger.reserve_request(db, provider, reserved, expected_snapshot=approved, purpose=purpose,
        job_key=job_key, item_key=item_key, retry_generation=retry_generation, authorize=authorize)
    request_key = row.request_key
    db.rollback()
    try:
        result = (request or direct_image_request)(selected, prompt=prompt, system=system,
            image_size=image_size, image_quality=image_quality, api_key=key)
        data = result.get('data')
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict) or data[0].get('url'):
            raise ValueError('Image provider must return one inline base64 PNG, never a URL')
        body = decode_png(data[0].get('b64_json'), image_size)
    except Exception as exc:
        ledger.mark_unknown(db, request_key)
        raise ledger.ProviderRequestUnresolved('The portrait result is unavailable or invalid. Review its reservation before explicitly retrying; no provider URL was fetched.') from exc
    ledger.settle_request(db, request_key, charged=reserved, input_tokens=0, output_tokens=0)
    return body, 'image/png', reserved


def direct_image_request(provider, *, prompt, system, image_size, image_quality, api_key):
    import json
    headers = {'Content-Type': 'application/json'}
    if api_key: headers['Authorization'] = 'Bearer ' + api_key
    payload = {'model': provider.image_model, 'prompt': system + '\n\n' + prompt, 'n': 1,
        'size': image_size, 'quality': image_quality, 'output_format': 'png'}
    transport = httpx.HTTPTransport() if provider.kind == 'local' else public_http_transport(force_public=True)
    with httpx.Client(transport=transport, timeout=httpx.Timeout(180, connect=8), follow_redirects=False, trust_env=False) as client:
        with client.stream('POST', provider.base_url.rstrip('/') + '/images/generations', json=payload, headers=headers) as response:
            if response.status_code >= 300: raise ValueError('Image provider rejected the request')
            body = bytearray()
            for chunk in response.iter_bytes(64 * 1024):
                body.extend(chunk)
                if len(body) > 11_200_000: raise ValueError('Image provider response exceeds its limit')
            return json.loads(body)
