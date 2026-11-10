"""Aggregate-only dashboard downloads, generated from the same query as the UI."""
import colorsys
import csv
import io
import json
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from . import bd_exec as db

PALETA = ['#0f766e', '#2563eb', '#d97706', '#9333ea', '#e11d48', '#0891b2', '#4d7c0f', '#c2410c', '#7c3aed', '#475569']


def cor(index):
    if index < len(PALETA):
        return PALETA[index]
    rgb = colorsys.hls_to_rgb((index * 137.508 % 360) / 360, .42, .6)
    return '#' + ''.join(f'{round(value * 255):02x}' for value in rgb)


def parametros(data):
    if not isinstance(data, dict) or type(data.get('quiz_id')) is not int:
        raise ValueError('Questionário inválido.')
    if data.get('format') not in ('pdf', 'csv', 'json') or data.get('mode') not in ('filtered', 'simple'):
        raise ValueError('Formato ou modo inválido.')
    filters = data.get('filters', {}) if data['mode'] == 'filtered' else {}
    profiles = data.get('profiles', []) if data['mode'] == 'filtered' else []
    if not isinstance(filters, dict):
        raise ValueError('Filtros inválidos.')
    return data['quiz_id'], filters, profiles


def preparar(data):
    return formatar(data, db.resultados_questionario(*parametros(data)))


async def preparar_async(data, database):
    result = await database.resultados_questionario(*parametros(data))
    return formatar(data, result)


def formatar(data, result):
    if result is None:
        raise ValueError('Questionário não encontrado.')
    available = {str(chart['id']): chart for chart in result['charts']}
    selected = data.get('charts', 'all')
    if selected == 'all':
        selected = list(available)
    elif (not isinstance(selected, list) or not selected or
          any(not isinstance(key, str) or key not in available for key in selected)):
        raise ValueError('Selecione gráficos válidos para exportar.')
    if not selected:
        raise ValueError('Não há gráficos para exportar.')
    orders = data.get('orders', {})
    if not isinstance(orders, dict) or any(key not in available or value not in ('asc', 'desc') for key, value in orders.items()):
        raise ValueError('Ordenação inválida.')
    applied = []
    for chart in result['charts']:
        labels = [option['label'] for option in chart['options'] if option['selected']]
        if labels:
            applied.append(dict(chart=str(chart['id']), title=chart['title'], options=labels))
    charts = []
    for key, chart in available.items():
        if key not in selected:
            continue
        options = [dict(**option, color=cor(index), percentage=100 * option['count'] / chart['base'] if chart['base'] else 0)
                   for index, option in enumerate(chart['options'])]
        options.sort(key=lambda option: option['count'], reverse=orders.get(key, 'desc') == 'desc')
        charts.append(dict(id=key, title=chart['title'], base=chart['base'], options=options))
    return dict(quiz_id=data['quiz_id'], title=result['title'], generated_at=datetime.now(UTC).isoformat(),
                mode=data['mode'], filters=applied, total=result['total'], matching=result['matching'], charts=charts)


def gerar_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')


def gerar_csv(data):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(['questionario', 'gerado_em_utc', 'modo', 'filtros', 'total_envios', 'envios_filtrados',
                     'grafico_id', 'pergunta', 'alternativa', 'contagem', 'percentual', 'selecionada'])
    filters = json.dumps(data['filters'], ensure_ascii=False)
    def safe(value):
        # Prevent spreadsheet formulas in user-authored titles and option labels.
        return "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value
    for chart in data['charts']:
        for option in chart['options']:
            writer.writerow([safe(value) for value in [data['title'], data['generated_at'], data['mode'], filters,
                data['total'], data['matching'], chart['id'], chart['title'], option['label'], option['count'],
                f"{option['percentage']:.2f}", option['selected']]])
    return stream.getvalue().encode('utf-8-sig')


def gerar_pdf(data):
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    stream = io.BytesIO()
    styles = getSampleStyleSheet()
    paragraph = lambda text, style='BodyText': Paragraph(escape(str(text)), styles[style])
    story = [paragraph(data['title'], 'Title'), paragraph(f"Gerado em UTC: {data['generated_at']}"),
             paragraph('Com filtro atual' if data['mode'] == 'filtered' else 'Exportação simples — sem filtros'),
             paragraph(f"Envios: {data['matching']} de {data['total']}")]
    for entry in data['filters']:
        story.append(paragraph(entry['title'] + ': ' + ' OU '.join(entry['options'])))
    for index, chart in enumerate(data['charts']):
        if index:
            story.append(PageBreak())
        story.extend([Spacer(1, 16), paragraph(chart['title'], 'Heading2'), paragraph(f"Base: {chart['base']} respostas")])
        nonzero = [option for option in chart['options'] if option['count']]
        if nonzero:
            drawing = Drawing(460, 250)
            pie = Pie()
            pie.x, pie.y, pie.width, pie.height = 140, 35, 180, 180
            pie.data = [option['count'] for option in nonzero]
            pie.labels = [f"{option['percentage']:.1f}%" for option in nonzero]
            pie.sideLabels = True
            for i, option in enumerate(nonzero):
                pie.slices[i].fillColor = colors.HexColor(option['color'])
                pie.slices[i].strokeColor = colors.white
            drawing.add(pie)
            story.append(drawing)
        else:
            story.append(paragraph('Sem respostas para os filtros escolhidos.'))
        rows = [['Cor', 'Alternativa', 'Contagem', '%']]
        for option in chart['options']:
            rows.append(['', paragraph(('[Selecionada] ' if option['selected'] else '') + option['label']),
                         str(option['count']), f"{option['percentage']:.1f}%"])
        table = Table(rows, colWidths=[25, 315, 65, 55], repeatRows=1, hAlign='LEFT')
        commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e2e8f0')),
                    ('LINEBELOW', (0, 0), (-1, -1), .3, colors.HexColor('#cbd5e1')),
                    ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]
        for i, option in enumerate(chart['options'], 1):
            commands.append(('BACKGROUND', (0, i), (0, i), colors.HexColor(option['color'])))
        table.setStyle(TableStyle(commands))
        story.append(table)
    def footer(canvas, document):
        canvas.setFont('Helvetica', 9)
        canvas.drawRightString(540, 25, f'Página {document.page}')
    SimpleDocTemplate(stream, title=data['title'], leftMargin=48, rightMargin=48,
                      topMargin=40, bottomMargin=40).build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
