// Optional DOM smoke test for the portable checker page. Uses existing frontend deps.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM, VirtualConsole } = require('../frontend/node_modules/jsdom');
const errors = [];
const console = new VirtualConsole();
console.on('jsdomError', error => errors.push(error));
const dom = new JSDOM(fs.readFileSync(process.argv[2], 'utf8'), {
  runScripts: 'dangerously', url: 'https://offline-review.invalid/', virtualConsole: console,
  beforeParse(window) {
    window.HTMLMediaElement.prototype.pause = () => {};
    window.HTMLMediaElement.prototype.play = () => Promise.resolve();
    window.prompt = () => 'The selected word is pronounced incorrectly';
    window.alert = () => {};
  }
});
const { document, Event } = dom.window;
assert.match(document.querySelector('#title').textContent, /v\d+/);
assert.ok(document.querySelectorAll('#cards article').length > 0);
document.querySelector('[data-report]').click();
assert.match(document.querySelector('#notes').textContent, /pronounced incorrectly/);
const input = document.querySelector('#search');
input.value = 'this phrase cannot occur in the test book';
input.dispatchEvent(new Event('input'));
assert.ok([...document.querySelectorAll('#cards article')].every(a => a.hidden));
input.value = '';
input.dispatchEvent(new Event('input'));
assert.ok([...document.querySelectorAll('#cards article')].every(a => !a.hidden));
document.querySelector('[data-start]').click();
assert.match(document.querySelector('#player').src, /audiobook\.mp3$/);
assert.equal(errors.length, 0, errors.map(e => e.message).join('\n'));
dom.window.close();
process.stdout.write('Review pack DOM smoke test passed\n');
