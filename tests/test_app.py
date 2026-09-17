from dataclasses import replace
import time
from fastapi.testclient import TestClient
import app.main as main

client = TestClient(main.app)


def test_health_endpoint():
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'


def test_home_page_loads():
    response = client.get('/')
    assert response.status_code == 200
    assert 'Keep the document.' in response.text
    assert '.docx' in response.text
    assert '.progress[hidden], .result[hidden] { display: none; }' in response.text
    assert 'id="model"' in response.text
    assert 'fileModel' not in response.text
    assert 'textModel' not in response.text


def test_private_routes_require_authentication(monkeypatch):
    monkeypatch.setattr(main, 'settings', replace(main.settings, hosted=True, username='team', password='a-long-private-password'))
    assert client.get('/').status_code == 401
    assert client.get('/api/config').status_code == 401
    assert client.get('/api/download/example.pdf').status_code == 401
    assert client.get('/api/health').status_code == 200
    assert client.get('/api/config', auth=('team', 'a-long-private-password')).status_code == 200


def test_async_txt_rewrite_and_download(tmp_path, monkeypatch):
    config = replace(main.settings, upload_dir=tmp_path / 'uploads', output_dir=tmp_path / 'output', hosted=False, password='')
    config.ensure_directories()
    monkeypatch.setattr(main, 'settings', config)
    monkeypatch.setattr(main.Humanizer, 'rewrite', lambda self, blocks: {b.id: 'Clear text' for b in blocks})
    response = client.post('/api/rewrite', files={'file': ('example.txt', b'Original wording\r\n', 'text/plain')})
    assert response.status_code == 202
    url = response.json()['status_url']
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(url).json()
        if job['status'] in ('complete', 'failed'):
            break
        time.sleep(.01)
    assert job['status'] == 'complete', job
    assert client.get(job['download_url']).content == b'Clear text\r\n'
    assert client.get(job['report_url']).json()['model'] == config.model


def test_configuration_orders_the_default_model_first(monkeypatch):
    config = replace(
        main.settings,
        model='gpt-5.6-terra',
        allowed_models=('gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-6-astra'),
    )
    monkeypatch.setattr(main, 'settings', config)
    response = client.get('/api/config')
    assert response.json()['model'] == 'gpt-5.6-terra'
    assert response.json()['models'] == list(config.allowed_models)


def test_rewrite_text_returns_an_editable_rewrite(monkeypatch):
    monkeypatch.setattr(
        main.Humanizer,
        'rewrite',
        lambda self, blocks: {block.id: 'Clearer wording' for block in blocks},
    )
    response = client.post(
        '/api/rewrite-text',
        data={'text': 'Original wording', 'model': main.settings.model},
    )
    assert response.status_code == 200
    assert response.json() == {
        'original': 'Original wording',
        'rewritten': 'Clearer wording',
        'model': main.settings.model,
    }


def test_rewrite_text_rejects_empty_text_and_unknown_model():
    assert client.post('/api/rewrite-text', data={'text': '   '}).status_code == 400
    assert client.post('/api/rewrite-text', data={'text': 'Text', 'model': 'unconfigured-model'}).status_code == 400


def test_rejects_unknown_format_model_and_cross_site_upload():
    assert client.post('/api/rewrite', files={'file': ('old.doc', b'content')}).status_code == 400
    assert client.post('/api/rewrite', files={'file': ('ok.txt', b'content')}, data={'model': 'unconfigured-model'}).status_code == 400
    assert client.post('/api/rewrite', files={'file': ('ok.txt', b'content')}, headers={'Origin': 'https://untrusted.example'}).status_code == 403


def test_retention_preserves_active_jobs(tmp_path, monkeypatch):
    config = replace(main.settings, upload_dir=tmp_path/'uploads', output_dir=tmp_path/'output', retention_hours=1)
    config.ensure_directories()
    monkeypatch.setattr(main, 'settings', config)
    import os
    for name in ('expired-file.txt', 'active-file.txt'):
        path = config.upload_dir / name
        path.write_text('text')
        os.utime(path, (1, 1))
    monkeypatch.setattr(main, 'jobs', {'active': {'status': 'processing', 'created_at': 1}})
    main._cleanup()
    assert not (config.upload_dir/'expired-file.txt').exists()
    assert (config.upload_dir/'active-file.txt').exists()


def test_hosted_startup_refuses_unprotected_configuration(monkeypatch):
    import pytest
    monkeypatch.setattr(main, 'settings', replace(main.settings, hosted=True, username='', password='', retention_hours=24))
    with pytest.raises(RuntimeError, match='APP_USERNAME'):
        with TestClient(main.app):
            pass
