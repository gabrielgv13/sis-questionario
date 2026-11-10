(() => {
  'use strict';
  const manager = document.querySelector('#questionnaire-manager');
  const search = document.querySelector('#questionnaire-search');
  const status = document.querySelector('#questionnaire-status');
  const cards = [...manager.querySelectorAll('.questionnaire-card')];
  const dialog = document.querySelector('#management-dialog');
  const file = document.querySelector('#questionnaire-file');
  const algorithmFile = document.querySelector('#algorithm-file');
  const algorithmFields = document.querySelector('#management-algorithm-fields');
  const algorithmDescription = document.querySelector('#management-algorithm-description');
  let questionnaire = null, selectionRevision = 0;
  const fileStatus = document.querySelector('#management-file-status');
  const confirm = document.querySelector('#management-confirm');
  let currentAction, exportUrl, busy = false;
  const normalize = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
  function filter() {
    const query = normalize(search.value.trim());
    let count = 0;
    for (const card of cards) {
      const matches = normalize(`${card.dataset.title} ${card.dataset.code}`).includes(query) &&
        (status.value === 'all' || card.dataset.status === status.value);
      card.hidden = !matches;
      if (matches) count++;
    }
    document.querySelector('#questionnaire-count').textContent = `${count} questionário(s)`;
    document.querySelector('#questionnaire-empty').hidden = count !== 0;
  }
  search.addEventListener('input', filter);
  status.addEventListener('change', filter);
  manager.addEventListener('click', event => {
    const button = event.target.closest('[data-management-action]');
    if (!button || busy) return;
    const action = button.dataset.managementAction;
    const title = button.closest('.questionnaire-card')?.dataset.title;
    const content = {
      import: ['Importar questionário', 'Selecione um JSON no padrão v1. Um novo questionário será criado; códigos existentes não serão sobrescritos. O arquivo será salvo no banco junto com as perguntas e alternativas.', 'Importar'],
      export_algorithm: ['Exportar algoritmo', 'Baixe as regras de pontuação para importar junto com o questionário.', 'Exportar algoritmo'],
      export: ['Exportar questionário', `Baixe a estrutura de “${title}” em JSON v1, incluindo suas configurações. Respostas e dados dos participantes não são incluídos.`, 'Exportar JSON'],
      delete: ['Excluir questionário', `Ao excluir “${title}”, suas perguntas, alternativas, envios e respostas também serão removidos do banco. Essa operação será definitiva quando estiver disponível.`, 'Excluir (em breve)'],
    }[action];
    if (!content) return;
    document.querySelector('#management-dialog-title').textContent = content[0];
    document.querySelector('#management-dialog-description').textContent = content[1];
    currentAction = action;
    exportUrl = button.dataset.export || button.closest('.questionnaire-card')?.dataset.export;
    confirm.textContent = content[2];
    confirm.disabled = !action.startsWith('export');
    document.querySelector('#management-import-fields').hidden = action !== 'import';
    file.value = ''; algorithmFile.value = ''; questionnaire = null; selectionRevision++;
    algorithmFields.hidden = true; algorithmFile.required = false;
    fileStatus.textContent = action === 'import' ? 'Selecione um arquivo para preparar a importação.' : action === 'delete' ? 'Esta ação ainda não está habilitada. Nenhum dado será excluído.' : '';
    dialog.showModal();
  });
  const validFile = chosen => chosen && chosen.name.toLowerCase().endsWith('.json') && chosen.size <= 1024 * 1024;
  function updateReady() {
    const requiresAlgorithm = Boolean(questionnaire?.algoritmo);
    confirm.disabled = busy || !questionnaire || !validFile(file.files[0]) || (requiresAlgorithm && !validFile(algorithmFile.files[0]));
    if (requiresAlgorithm && !validFile(algorithmFile.files[0])) {
      fileStatus.textContent = 'Selecione o arquivo JSON do algoritmo para continuar (até 1 MiB).';
    } else if (questionnaire) {
      fileStatus.textContent = 'Arquivos selecionados. Clique em Importar para validar e salvar.';
    }
  }
  file.addEventListener('change', async () => {
    const revision = ++selectionRevision;
    const chosen = file.files[0];
    questionnaire = null; confirm.disabled = true;
    algorithmFile.value = ''; algorithmFields.hidden = true; algorithmFile.required = false;
    if (!validFile(chosen)) {
      fileStatus.textContent = 'Selecione um arquivo .json de até 1 MiB.';
      return;
    }
    try {
      const parsed = JSON.parse(await chosen.text());
      if (revision !== selectionRevision) return;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) ||
          !Object.hasOwn(parsed, 'algoritmo') ||
          (parsed.algoritmo !== null && (typeof parsed.algoritmo !== 'string' || !parsed.algoritmo.trim()))) {
        throw new Error('O questionário deve informar algoritmo como null ou uma string preenchida.');
      }
      questionnaire = parsed;
      algorithmFields.hidden = !parsed.algoritmo;
      algorithmFile.required = Boolean(parsed.algoritmo);
      algorithmDescription.textContent = parsed.algoritmo ? `Este questionário exige o algoritmo “${parsed.algoritmo}”. A version do arquivo deve corresponder a esse identificador.` : '';
      updateReady();
    } catch (error) {
      if (revision === selectionRevision) fileStatus.textContent = error instanceof SyntaxError ? 'Arquivo JSON inválido.' : error.message;
    }
  });
  algorithmFile.addEventListener('change', updateReady);
  confirm.addEventListener('click', async () => {
    if (busy || currentAction === 'delete') return;
    const importing = currentAction === 'import';
    if (importing && (!questionnaire || !validFile(file.files[0]) || (questionnaire.algoritmo && !validFile(algorithmFile.files[0])))) return;
    busy = true; confirm.disabled = true; file.disabled = true; algorithmFile.disabled = true;
    fileStatus.textContent = importing ? 'Validando e importando…' : 'Preparando download…';
    try {
      const form = new FormData();
      if (importing) {
        form.append('file', file.files[0]);
        if (questionnaire.algoritmo) form.append('algorithm', algorithmFile.files[0]);
      }
      const response = await fetch(importing ? manager.dataset.import : exportUrl,
        importing ? {method: 'POST', headers: {'X-CSRF-Token': manager.dataset.token}, body: form} : {});
      if (response.status === 401) { window.location.assign('/admin/login'); return; }
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Não foi possível concluir a operação. Atualize a página e tente novamente.');
      }
      if (importing) { window.location.reload(); return; }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url; link.download = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] || 'questionario.json';
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      fileStatus.textContent = 'Download iniciado.';
    } catch (error) { fileStatus.textContent = error.message; }
    finally {
      busy = false; file.disabled = false; algorithmFile.disabled = false;
      confirm.disabled = importing && (!questionnaire || !validFile(file.files[0]) ||
        (questionnaire.algoritmo && !validFile(algorithmFile.files[0])));
    }
  });
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => { selectionRevision++; });
})();
