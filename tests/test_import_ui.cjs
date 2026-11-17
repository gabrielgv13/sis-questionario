const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function page() {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      events: {}, files: [], dataset: {}, value: '', hidden: false, disabled: false,
      textContent: '', required: false,
      addEventListener(name, callback) { this.events[name] = callback; },
      querySelectorAll() { return []; }, showModal() {}, close() {},
    });
    return elements.get(id);
  }
  element('#questionnaire-manager').dataset = {import: '/import', token: 'csrf'};
  const uploads = [];
  const context = vm.createContext({
    document: {querySelector: element},
    window: {location: {reload() {}, assign() {}}},
    FormData: class { append(...entry) { uploads.push(entry); } },
    fetch: async () => ({ok: false, status: 400, json: async () => ({error: 'Regras incompatíveis'})}),
    setTimeout, URL, console,
  });
  vm.runInContext(fs.readFileSync('src/sis_questionario/static/js/admin_questionarios.js', 'utf8'), context);
  const button = {dataset: {managementAction: 'import'}, closest: () => null};
  element('#questionnaire-manager').events.click({target: {closest: () => button}});
  async function select(algorithm) {
    element('#questionnaire-file').files = [{name: 'quiz.json', size: 100,
      text: async () => JSON.stringify({algoritmo: algorithm})}];
    await element('#questionnaire-file').events.change();
  }
  return {element, select, uploads};
}

test('algorithm identifier requires second file before import is enabled', async () => {
  const {element, select, uploads} = page();
  await select('perfil_v1');
  assert.equal(element('#management-algorithm-fields').hidden, false);
  assert.equal(element('#management-confirm').disabled, true);
  assert.match(element('#management-algorithm-description').textContent, /perfil_v1/);
  element('#algorithm-file').files = [{name: 'perfil_v1.json', size: 100}];
  element('#algorithm-file').events.change();
  assert.equal(element('#management-confirm').disabled, false);
  await element('#management-confirm').events.click();
  assert.deepEqual(uploads.map(([key]) => key), ['file', 'algorithm']);
  assert.equal(element('#management-file-status').textContent, 'Regras incompatíveis');
});

test('questionnaire without algorithm needs only one file', async () => {
  const {element, select} = page();
  await select(null);
  assert.equal(element('#management-algorithm-fields').hidden, true);
  assert.equal(element('#management-confirm').disabled, false);
});

test('changing questionnaire discards stale algorithm selection', async () => {
  const {element, select} = page();
  await select('first');
  element('#algorithm-file').files = [{name: 'first.json', size: 100}];
  element('#algorithm-file').events.change();
  // Browsers clear FileList when value is reset; emulate this for the fixture.
  Object.defineProperty(element('#algorithm-file'), 'value', {
    set() { this.files = []; }, get() { return ''; },
  });
  await select('second');
  assert.equal(element('#management-confirm').disabled, true);
  assert.equal(element('#algorithm-file').files.length, 0);
});
