"""Shared HTTP helpers for the FastAPI routes."""
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

templates = Jinja2Templates(directory=Path(__file__).with_name('templates'))


def abort(status_code, description=None):
    raise HTTPException(status_code, detail=description)


def redirect(request: Request, name: str):
    return RedirectResponse(request.url_for(name), status_code=302)


async def render_template(request: Request, name: str, status_code=200, **context):
    return await run_in_threadpool(
        templates.TemplateResponse, request=request, name=name,
        context={'session': request.scope.get('session', {}), **context}, status_code=status_code,
    )


async def read_json(request: Request):
    media_type = request.headers.get('content-type', '').split(';')[0].strip().lower()
    if media_type != 'application/json' and not (media_type.startswith('application/') and media_type.endswith('+json')):
        abort(415)
    try:
        return await request.json()
    except ValueError:
        abort(400, 'JSON inválido.')
