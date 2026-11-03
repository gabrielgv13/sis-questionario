(() => {
  'use strict';
  const manager = document.querySelector('#questionnaire-manager');
  const search = document.querySelector('#questionnaire-search');
  const status = document.querySelector('#questionnaire-status');
  const cards = [...manager.querySelectorAll('.questionnaire-card')];
  const dialog = document.querySelector('#management-dialog');
  const file = document.querySelector('#questionnaire-file');
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
      export: ['Exportar questionário', `Baixe a estrutura de “${title}” em JSON v1, incluindo suas configurações. Respostas e dados dos participantes não são incluídos.`, 'Exportar JSON'],
      delete: ['Excluir questionário', `Ao excluir “${title}”, suas perguntas, alternativas, envios e respostas também serão removidos do banco. Essa operação será definitiva quando estiver disponível.`, 'Excluir (em breve)'],
    }[action];
    if (!content) return;
    document.querySelector('#management-dialog-title').textContent = content[0];
    document.querySelector('#management-dialog-description').textContent = content[1];
    currentAction = action;
    exportUrl = button.closest('.questionnaire-card')?.dataset.export;
    confirm.textContent = content[2];
    confirm.disabled = action !== 'export';
    document.querySelector('#management-import-fields').hidden = action !== 'import';
    file.value = '';
    fileStatus.textContent = action === 'import' ? 'Selecione um arquivo para preparar a importação.' : action === 'delete' ? 'Esta ação ainda não está habilitada. Nenhum dado será excluído.' : '';
    dialog.showModal();
  });
  file.addEventListener('change', () => {
    const chosen = file.files[0];
    const valid = chosen && chosen.name.toLowerCase().endsWith('.json') && chosen.size <= 1024 * 1024;
    confirm.disabled = !valid || busy;
    fileStatus.textContent = valid ? `Arquivo selecionado: ${chosen.name}. Clique em Importar para validar e salvar.` : 'Selecione um arquivo .json de até 1 MiB.';
  });
  confirm.addEventListener('click', async () => {
    if (busy || currentAction === 'delete') return;
    const importing = currentAction === 'import';
    if (importing && !file.files[0]) return;
    busy = true; confirm.disabled = true; file.disabled = true;
    fileStatus.textContent = importing ? 'Validando e importando…' : 'Preparando download…';
    try {
      const form = new FormData();
      if (importing) form.append('file', file.files[0]);
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
    finally { busy = false; confirm.disabled = false; file.disabled = false; }
  });
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
})();
