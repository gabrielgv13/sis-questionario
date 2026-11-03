(() => {
  'use strict';
  const root = document.querySelector('#admin-dashboard');
  const quiz = document.querySelector('#quiz');
  const charts = document.querySelector('#charts');
  const status = document.querySelector('#admin-status');
  const chips = document.querySelector('#active-filters');
  let filters = {}, profileFilters = [], controller, version = 0;
  const setting = document.querySelector('#result-setting');
  const showResult = document.querySelector('#show-result');
  const number = new Intl.NumberFormat('pt-BR');
  const legendOrders = new Map();
  let currentCharts = [], exporting = false;
  const exportPanel = document.querySelector('#export-panel');
  const openExport = document.querySelector('#open-export');
  const exportChoices = document.querySelector('#export-choices');
  const downloadExport = document.querySelector('#download-export');
  const exportStatus = document.querySelector('#export-status');
  const modes = [...document.querySelectorAll('[name="export-mode"]')];
  modes.forEach(input => input.addEventListener('change', () => {
    modes.forEach(other => { other.checked = other === input; });
  }));
  function exportSelection() {
    const all = exportChoices.querySelector('[value="all"]');
    const options = [...exportChoices.querySelectorAll('input:not([value="all"])')];
    if (options.length && options.every(input => input.checked)) {
      all.checked = true;
      options.forEach(input => { input.checked = false; });
    }
    const count = all?.checked ? options.length : options.filter(input => input.checked).length;
    document.querySelector('#export-summary').textContent = `Gráficos para exportar: ${all?.checked ? 'Todos' : count + ' selecionados'}`;
    downloadExport.disabled = exporting || !count;
    return all?.checked ? 'all' : options.filter(input => input.checked).map(input => input.value);
  }
  openExport.addEventListener('click', () => {
    exportPanel.hidden = !exportPanel.hidden;
    openExport.setAttribute('aria-expanded', String(!exportPanel.hidden));
    if (exportPanel.hidden) return;
    const filtered = profileFilters.length > 0 || Object.values(filters).some(values => values.length);
    modes.forEach(input => { input.checked = input.value === (filtered ? 'filtered' : 'simple'); });
    document.querySelector('#export-format').value = 'pdf';
    exportStatus.textContent = '';
    exportChoices.replaceChildren();
    for (const choice of [{id: 'all', title: 'Todos'}, ...currentCharts]) {
      const label = element('label');
      const input = element('input');
      input.type = 'checkbox'; input.value = String(choice.id); input.checked = choice.id === 'all';
      input.addEventListener('change', () => {
        if (input.checked) {
          if (input.value === 'all') exportChoices.querySelectorAll('input').forEach(other => { other.checked = other === input; });
          else exportChoices.querySelector('[value="all"]').checked = false;
        }
        exportSelection();
      });
      label.append(input, document.createTextNode(' ' + choice.title));
      exportChoices.append(label);
    }
    exportSelection();
  });
  exportPanel.addEventListener('submit', async event => {
    event.preventDefault();
    if (exporting) return;
    const selected = exportSelection();
    if (Array.isArray(selected) && !selected.length) { exportStatus.textContent = 'Selecione pelo menos um gráfico.'; return; }
    const quizId = Number(quiz.value), format = document.querySelector('#export-format').value;
    const payload = {quiz_id: quizId, format, mode: modes.find(input => input.checked).value,
      charts: selected, filters, profiles: profileFilters,
      orders: Object.fromEntries(currentCharts.map(chart => [String(chart.id), legendOrders.get(`${quiz.value}:${chart.id}`) || 'desc']))};
    exporting = true; downloadExport.disabled = true;
    exportStatus.textContent = 'Gerando arquivo…';
    try {
      const response = await fetch(root.dataset.export, {method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': root.dataset.token}, body: JSON.stringify(payload)});
      if (response.status === 401) { window.location.assign('/admin/login'); return; }
      if (!response.ok) throw new Error('Não foi possível exportar. Confira as opções e tente novamente.');
      const url = URL.createObjectURL(await response.blob());
      const link = element('a'); link.href = url; link.download = `questionario-${quizId}.${format}`;
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      exportStatus.textContent = 'Arquivo gerado. Download iniciado.';
    } catch (error) { exportStatus.textContent = error.message; }
    finally { exporting = false; exportSelection(); }
  });
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function toggle(question, option) {
    if (question === 'profiles') {
      profileFilters = profileFilters.includes(option) ? profileFilters.filter(id => id !== option) : [...profileFilters, option];
      update();
      return;
    }
    const selected = filters[question] || [];
    filters[question] = selected.includes(option) ? selected.filter(id => id !== option) : [...selected, option];
    if (!filters[question].length) delete filters[question];
    update();
  }
  function svgNode(tag, attributes, text) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function drawPie(pie, slices) {
    const sides = [[], []];
    for (const slice of slices) {
      const radians = ((slice.start + slice.end) / 2 - 90) * Math.PI / 180;
      slice.dx = Math.cos(radians); slice.dy = Math.sin(radians);
      sides[slice.dx < 0 ? 0 : 1].push(slice);
    }
    const height = Math.max(240, Math.max(...sides.map(side => side.length)) * 18 + 24);
    const cy = height / 2, cx = 160, radius = 78;
    const svg = svgNode('svg', {viewBox: `0 0 320 ${height}`, 'aria-hidden': 'true'});
    for (const slice of slices) {
      const point = angle => [cx + radius * Math.cos((angle - 90) * Math.PI / 180), cy + radius * Math.sin((angle - 90) * Math.PI / 180)];
      const start = point(slice.start), end = point(slice.end);
      const shape = slice.end - slice.start > 359.999
        ? svgNode('circle', {cx, cy, r: radius, fill: slice.color})
        : svgNode('path', {d: `M ${cx} ${cy} L ${start.join(' ')} A ${radius} ${radius} 0 ${slice.end - slice.start > 180 ? 1 : 0} 1 ${end.join(' ')} Z`, fill: slice.color, stroke: '#fff', 'stroke-width': 1});
      shape.append(svgNode('title', {}, `${slice.label}: ${slice.percent}`));
      svg.append(shape);
    }
    sides.forEach((side, index) => {
      side.sort((a, b) => a.dy - b.dy);
      let previous = -6;
      const positions = side.map(slice => {
        const y = Math.max(12, previous + 18, cy + slice.dy * 104);
        previous = y;
        return y;
      });
      // Move crowded labels back into the viewport without overlapping them.
      for (let i = positions.length - 1; i >= 0; i--) {
        positions[i] = Math.min(positions[i], i === positions.length - 1 ? height - 12 : positions[i + 1] - 18);
      }
      side.forEach((slice, i) => {
        const x = index ? 268 : 52, y = positions[i];
        svg.append(svgNode('polyline', {
          points: `${cx + slice.dx * 74},${cy + slice.dy * 74} ${cx + slice.dx * 94},${cy + slice.dy * 94} ${x},${y}`,
          fill: 'none', stroke: slice.color, 'stroke-width': 1.5,
        }));
        const label = svgNode('text', {x: index ? 272 : 48, y, 'text-anchor': index ? 'start' : 'end', 'dominant-baseline': 'middle', class: 'pie-percent'}, slice.percent);
        label.append(svgNode('title', {}, slice.label));
        svg.append(label);
      });
    });
    pie.append(svg);
  }
  async function update() {
    if (!quiz.value) { status.textContent = 'Nenhum questionário cadastrado.'; return; }
    controller?.abort();
    controller = new AbortController();
    const current = ++version;
    const focused = document.activeElement?.dataset.focus;
    const scrollPositions = new Map([...charts.querySelectorAll('.pie-legend')].map(legend => [legend.dataset.question, legend.scrollTop]));
    charts.setAttribute('aria-busy', 'true');
    openExport.disabled = true;
    showResult.disabled = true;
    charts.querySelectorAll('button').forEach(button => { button.disabled = true; });
    status.className = '';
    status.textContent = 'Carregando respostas…';
    try {
      const response = await fetch(root.dataset.endpoint, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': root.dataset.token},
        body: JSON.stringify({quiz_id: Number(quiz.value), filters, profiles: profileFilters}), signal: controller.signal,
      });
      if (response.status === 401) { window.location.assign('/admin/login'); return; }
      if (!response.ok) throw new Error('Não foi possível carregar os resultados. Atualize a página ou tente novamente.');
      const data = await response.json();
      if (current !== version) return;
      currentCharts = data.charts;
      openExport.disabled = !currentCharts.length;
      setting.hidden = !data.algorithm;
      showResult.checked = data.show_result;
      showResult.disabled = false;
      document.querySelector('#total').textContent = number.format(data.total);
      document.querySelector('#matching').textContent = number.format(data.matching);
      charts.replaceChildren(); chips.replaceChildren();
      for (const chart of data.charts) {
        const card = element('section', undefined, 'admin-card');
        const heading = element('h2', chart.title);
        heading.id = `question-${chart.id}`;
        card.setAttribute('aria-labelledby', heading.id);
        card.append(heading, element('p', `${number.format(chart.base)} respostas considerando todos os filtros.`));
        const layout = element('div', undefined, 'pie-layout');
        const pie = element('div', undefined, 'answer-pie');
        pie.setAttribute('role', 'img');
        pie.setAttribute('aria-label', chart.base ? `${chart.title}: distribuição das respostas. Valores na legenda ao lado.` : `${chart.title}: sem respostas para os filtros atuais.`);
        const legend = element('div', undefined, 'pie-legend');
        legend.dataset.question = String(chart.id);
        legend.tabIndex = 0;
        legend.setAttribute('role', 'group');
        legend.setAttribute('aria-label', `Filtrar: ${chart.title}`);
        const legendPanel = element('div', undefined, 'legend-panel');
        const orderButton = element('button', undefined, 'legend-order');
        orderButton.type = 'button';
        orderButton.dataset.focus = `order-${chart.id}`;
        const orderKey = `${quiz.value}:${chart.id}`;
        const legendEntries = [];
        function orderLegend(resetScroll = false) {
          const ascending = legendOrders.get(orderKey) === 'asc';
          // Counts and percentages have the same order within a chart.
          // Original position breaks ties and keeps colors independent of sorting.
          const entries = [...legendEntries].sort((a, b) =>
            (ascending ? a.count - b.count : b.count - a.count) || a.index - b.index);
          for (const entry of entries) legend.append(entry.button);
          orderButton.textContent = ascending ? '↑ Menor → maior' : '↓ Maior → menor';
          orderButton.setAttribute('aria-label', `${chart.title}: ordem ${ascending ? 'crescente' : 'decrescente'}. Clique para inverter.`);
          orderButton.title = 'Inverter a ordem das legendas por porcentagem';
          if (resetScroll) legend.scrollTo({top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
        }
        orderButton.addEventListener('click', () => {
          legendOrders.set(orderKey, legendOrders.get(orderKey) === 'asc' ? 'desc' : 'asc');
          orderLegend(true);
        });
        const palette = ['#0f766e', '#2563eb', '#d97706', '#9333ea', '#e11d48', '#0891b2', '#4d7c0f', '#c2410c', '#7c3aed', '#475569'];
        const slices = [];
        let angle = 0;
        for (const [index, option] of chart.options.entries()) {
          const color = index < palette.length ? palette[index] : `hsl(${(index * 137.508) % 360} 60% 42%)`;
          const percent = chart.base ? 100 * option.count / chart.base : 0;
          if (option.count) {
            const end = angle + percent * 3.6;
            slices.push({color, start: angle, end, label: option.label, percent: `${percent.toLocaleString('pt-BR', {maximumFractionDigits: 1})}%`});
            angle = end;
          }
          const value = `${number.format(option.count)} · ${percent.toLocaleString('pt-BR', {maximumFractionDigits: 1})}%`;
          const button = element('button', undefined, 'legend-option');
          button.type = 'button'; button.dataset.focus = `${chart.id}-${option.id}`;
          button.setAttribute('aria-pressed', String(option.selected));
          button.title = `${option.label}: ${value}. Clique para filtrar.`;
          const swatch = element('span', undefined, 'legend-swatch');
          swatch.style.backgroundColor = color;
          swatch.setAttribute('aria-hidden', 'true');
          const label = element('span', undefined, 'answer-label');
          label.append(element('span', `${option.selected ? '✓ ' : ''}${option.label}`), element('span', value, 'answer-value'));
          button.append(swatch, label);
          button.addEventListener('click', () => toggle(chart.id, option.id));
          legendEntries.push({button, count: option.count, index});
          if (option.selected) {
            const chip = element('button', `${chart.title}: ${option.label} ×`);
            chip.type = 'button'; chip.dataset.focus = `chip-${chart.id}-${option.id}`;
            chip.setAttribute('aria-label', `Remover filtro: ${chart.title}: ${option.label}`);
            chip.addEventListener('click', () => toggle(chart.id, option.id));
            chips.append(chip);
          }
        }
        if (slices.length) drawPie(pie, slices);
        if (!chart.base) pie.append(element('span', 'Sem respostas', 'pie-empty'));
        orderLegend();
        legendPanel.append(orderButton, legend);
        layout.append(pie, legendPanel);
        card.append(layout);
        charts.append(card);
        legend.scrollTop = scrollPositions.get(String(chart.id)) || 0;
      }
      status.textContent = data.total === 0 ? 'Este questionário ainda não recebeu respostas.' :
        data.matching === 0 ? 'Nenhum envio combina todos os filtros. Remova filtros para explorar outras combinações.' :
        `${number.format(data.matching)} de ${number.format(data.total)} envios combinam todos os filtros.`;
      if (focused) root.querySelector(`[data-focus="${focused}"]`)?.focus();
    } catch (error) {
      if (error.name !== 'AbortError' && current === version) {
        charts.replaceChildren(); chips.replaceChildren();
        document.querySelector('#matching').textContent = '—';
        document.querySelector('#total').textContent = '—';
        status.className = 'admin-error'; status.textContent = error.message;
      }
    } finally {
      if (current === version) charts.setAttribute('aria-busy', 'false');
    }
  }
  quiz.addEventListener('change', () => { filters = {}; profileFilters = []; setting.hidden = true; exportPanel.hidden = true; openExport.setAttribute('aria-expanded', 'false'); charts.replaceChildren(); chips.replaceChildren(); update(); });
  document.querySelector('#clear-filters').addEventListener('click', () => { filters = {}; profileFilters = []; update(); });
  document.querySelector('#refresh-results').addEventListener('click', update);
  showResult.addEventListener('change', async () => {
    showResult.disabled = true;
    quiz.disabled = true;
    try {
      const response = await fetch(root.dataset.settings, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': root.dataset.token},
        body: JSON.stringify({quiz_id: Number(quiz.value), show_result: showResult.checked}),
      });
      if (!response.ok) throw new Error('Não foi possível salvar a configuração. Tente novamente.');
      status.textContent = 'Configuração de devolutiva salva.';
    } catch (error) {
      showResult.checked = !showResult.checked;
      status.textContent = error.message;
    } finally { showResult.disabled = false; quiz.disabled = false; }
  });
  update();
})();
