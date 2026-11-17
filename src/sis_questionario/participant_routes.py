import secrets

from fastapi import APIRouter, Depends, Request

from .async_database import AsyncDatabase
from .async_pool import get_database
from .profile_scoring import DEFAULT_PROFILE_LABELS
from .sync_database import DuplicateSubmission
from .web import abort, redirect, render_template

router = APIRouter()


@router.get('/')
@router.head('/', include_in_schema=False)
async def index(request: Request, db: AsyncDatabase = Depends(get_database)):
    questionnaires = await db.list_active_questionnaires()
    return await render_template(request, 'index.html', questionarios=questionnaires)


@router.post('/submit-info', name='submit')
async def submit_participant_info(request: Request, db: AsyncDatabase = Depends(get_database)):
    form = await request.form()
    name = form.get('name', '')
    email = form.get('email', '')
    if not isinstance(name, str) or not isinstance(email, str):
        abort(400, description='Informe nome e e-mail válidos.')
    name = name.strip().title()
    email = email.strip().lower()
    try:
        questionnaire_id = int(form.get('questionario_id', ''))
    except (ValueError, TypeError):
        questionnaire_id = None
    if not name or not email or '@' not in email:
        abort(400, description='Informe nome e e-mail válidos.')
    if not await db.get_active_questionnaire(questionnaire_id):
        abort(400, description='Selecione um questionário disponível.')
    if await db.has_device_submitted(request.state.id_dispositivo, questionnaire_id):
        return await render_template(request, 'ja_respondido.html', status_code=409)

    participant_id = await db.register_participant(name, email)
    request.session.clear()
    request.session['aluno_id'] = participant_id
    request.session['questionario_id'] = questionnaire_id
    request.session['token_formulario'] = secrets.token_urlsafe(32)
    return redirect(request, 'pesquisa_perguntas')


@router.get('/pesquisa-perguntas', name='pesquisa_perguntas')
@router.head('/pesquisa-perguntas', name='pesquisa_perguntas', include_in_schema=False)
async def show_questionnaire(request: Request, db: AsyncDatabase = Depends(get_database)):
    questionnaire_id = request.session.get('questionario_id')
    if not request.session.get('aluno_id') or not questionnaire_id:
        return redirect(request, 'index')
    if await db.has_device_submitted(request.state.id_dispositivo, questionnaire_id):
        return await render_template(request, 'ja_respondido.html', status_code=409)
    questionnaire = await db.get_active_questionnaire(questionnaire_id)
    if not questionnaire:
        return redirect(request, 'index')
    return await render_template(
        request, 'perguntas.html', questionario=questionnaire, perguntas=questionnaire['perguntas'],
    )


@router.post('/submit-pesquisa', name='submit_pesquisa')
async def submit_answers(request: Request, db: AsyncDatabase = Depends(get_database)):
    participant_id = request.session.get('aluno_id')
    questionnaire_id = request.session.get('questionario_id')
    if not participant_id or not questionnaire_id:
        return redirect(request, 'index')

    form = await request.form()
    token = form.get('token_formulario', '')
    session_token = request.session.get('token_formulario', '')
    if not isinstance(token, str) or not token or not secrets.compare_digest(token, session_token):
        abort(400, description='Formulário inválido. Abra o questionário novamente.')

    answers = {}
    try:
        for field in form:
            if not field.startswith('pergunta_'):
                continue
            values = form.getlist(field)
            if len(values) != 1:
                raise ValueError('Selecione apenas uma opção por pergunta.')
            question_id = int(field.removeprefix('pergunta_'))
            answers[question_id] = int(values[0])
        submission_id = await db.save_submission(
            participant_id, questionnaire_id, answers, request.state.id_dispositivo,
        )
    except DuplicateSubmission:
        return await render_template(request, 'ja_respondido.html', status_code=409)
    except (ValueError, TypeError) as error:
        abort(400, description=str(error))

    request.session.pop('questionario_id', None)
    request.session.pop('token_formulario', None)
    request.session['envio_concluido'] = True
    request.session['envio_id'] = submission_id
    return redirect(request, 'concluido')


@router.get('/concluido', name='concluido')
@router.head('/concluido', name='concluido', include_in_schema=False)
async def show_submission_result(request: Request, db: AsyncDatabase = Depends(get_database)):
    if not request.session.get('envio_concluido'):
        return redirect(request, 'index')

    submission_id = request.session.get('envio_id')
    result = None
    if submission_id:
        result = await db.get_submission_result(submission_id, request.state.id_dispositivo)
    profiles = result.get('profiles', DEFAULT_PROFILE_LABELS) if result else DEFAULT_PROFILE_LABELS
    response = await render_template(request, 'concluido.html', resultado=result, perfis=profiles)
    response.headers['Cache-Control'] = 'no-store'
    return response
