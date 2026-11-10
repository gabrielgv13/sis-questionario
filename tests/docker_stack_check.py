"""HTTP checks for a disposable Docker stack. Run exercise, verify or unavailable."""
import json
import os
from pathlib import Path
import re
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.uv-cache/stack-state.json'
CLEAN_URL = os.environ.get('STACK_CLEAN_URL', 'http://127.0.0.1:5000')
PROFILE_URL = os.environ.get('STACK_PROFILE_URL', 'http://127.0.0.1:5001')


def login(client):
    page = client.get('/admin/login')
    assert page.status_code == 200
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    response = client.post('/admin/login', data={'csrf_token': token, 'password': os.environ['ADMIN_PASSWORD']})
    assert response.status_code == 302
    page = client.get('/admin/analise')
    assert page.status_code == 200
    return re.search(r'data-token="([^"]+)"', page.text)[1]


def exercise():
    rules = json.loads((ROOT / 'docs/perfil.template.json').read_text(encoding='utf-8'))
    quiz = json.loads((ROOT / 'docs/questionario.template.json').read_text(encoding='utf-8'))
    quiz.update(codigo='docker-validation', algoritmo=rules['version'], ativo=True, exibir_resultado=True)
    with httpx.Client(base_url=CLEAN_URL, timeout=15) as admin, httpx.Client(base_url=CLEAN_URL, timeout=15) as participant:
        csrf = login(admin)
        headers = {'X-CSRF-Token': csrf}
        files = {'file': ('questionario.json', json.dumps(quiz).encode(), 'application/json')}
        endpoint = '/admin/api/questionnaires/import'
        assert admin.post(endpoint, files=files, headers=headers).status_code == 400
        invalid = {**files, 'algorithm': ('algorithm.json', b'{}', 'application/json')}
        assert admin.post(endpoint, files=invalid, headers=headers).status_code == 400
        files['algorithm'] = ('algorithm.json', json.dumps(rules).encode(), 'application/json')
        response = admin.post(endpoint, files=files, headers=headers)
        assert response.status_code == 201, response.status_code
        identifier = response.json()['id']
        assert admin.get(f'/admin/api/questionnaires/{identifier}/export').json() == quiz
        assert admin.get(f'/admin/api/questionnaires/{identifier}/algorithm').json() == rules
        assert participant.get('/').status_code == 200
        response = participant.post('/submit-info', data={
            'name': 'Docker validation', 'email': 'docker-validation@example.com', 'questionario_id': identifier})
        assert response.status_code == 302
        page = participant.get('/pesquisa-perguntas')
        token = re.search(r'name="token_formulario" value="([^"]+)"', page.text)[1]
        choices = {}
        for question, option in re.findall(r'name="(pergunta_\d+)"[^>]*value="(\d+)"', page.text):
            choices.setdefault(question, option)
        assert len(choices) == len(quiz['perguntas'])
        assert participant.post('/submit-pesquisa', data={'token_formulario': token, **choices}).status_code == 302
        assert 'Nome do perfil A' in participant.get('/concluido').text
        assert participant.post('/submit-info', data={
            'name': 'Other', 'email': 'other@example.com', 'questionario_id': identifier}).status_code == 409
        for kind in ('json', 'csv', 'pdf'):
            response = admin.post('/admin/api/export', headers=headers,
                                  json={'quiz_id': identifier, 'format': kind, 'mode': 'simple'})
            assert response.status_code == 200
            assert response.headers['Cache-Control'] == 'no-store'
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps({'id': identifier, 'cookies': dict(participant.cookies)}), encoding='utf-8')
    verify()


def verify():
    state = json.loads(STATE.read_text(encoding='utf-8'))
    for url in (CLEAN_URL, PROFILE_URL):
        with httpx.Client(base_url=url, timeout=15) as client:
            assert client.get('/healthz').json() == {'status': 'ok'}
            assert client.get('/static/css/app.css').status_code == 200
            assert client.get('/static/js/admin_questionarios.js').status_code == 200
    with httpx.Client(base_url=CLEAN_URL, cookies=state['cookies'], timeout=15) as client:
        result = client.get('/concluido')
        assert result.status_code == 200
        assert 'Nome do perfil A' in result.text
        assert '40 pontos' in result.text
    with httpx.Client(base_url=CLEAN_URL, timeout=15) as admin:
        token = login(admin)
        response = admin.post('/admin/api/results', headers={'X-CSRF-Token': token},
                              json={'quiz_id': state['id'], 'profiles': ['perfil_a']})
        assert response.status_code == 200
        assert response.json()['matching'] == 1
        assert admin.get(f'/admin/api/questionnaires/{state["id"]}/algorithm').status_code == 200


def unavailable():
    response = httpx.get(CLEAN_URL + '/healthz', timeout=15)
    assert response.status_code == 503
    assert response.json() == {'status': 'unavailable'}


if __name__ == '__main__':
    {'exercise': exercise, 'verify': verify, 'unavailable': unavailable}[sys.argv[1]]()
    print('Stack HTTP check passed.')
