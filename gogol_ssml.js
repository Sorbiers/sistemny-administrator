'use strict';
// Готовит SSML для Silero теми же функциями, что и Gogolium (F:\Gogol):
//   num2ru.js  — числа словами;
//   rut2s.js   — ударения из словаря (+ перед гласной), паузы, разбивка на предложения.
// Код Gogolium не меняется: его файлы читаются и выполняются в отдельном контексте.
//
//   node gogol_ssml.js in.json out.json
// in.json  — массив строк (фрагменты главы);
// out.json — массив массивов: для каждого фрагмента список блоков <speak>…</speak> (по предложениям).

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { createRequire } = require('module');

const GOGOL = process.env.GOGOL_DIR || 'F:\\Gogol';
const APP = path.join(GOGOL, 'app');
const TTS = path.join(APP, 'tts');

function load(file, tail, dir) {
  let src = fs.readFileSync(file, 'utf-8').replace(/^#!.*\n/, '');
  const cut = src.indexOf('// === MAIN ===');      // num2ru.js сразу читает файл из argv — отрезаем
  if (cut >= 0) src = src.slice(0, cut);
  const mod = { exports: {} };
  const ctx = {
    require: createRequire(file), module: mod, exports: mod.exports,
    __dirname: dir, __filename: file, process,
    console: { log() {}, error() {}, warn() {} },
  };
  vm.runInNewContext(`${src}\n;module.__out = ${tail};`, ctx, { filename: file });
  return mod.__out;
}

const { replaceNumbers } = load(path.join(APP, 'num2ru.js'), '{ replaceNumbers }', APP);
const { RussianStressConverter, splitSentences, textToSsmlRuSimple } = load(
  path.join(TTS, 'rut2s.js'), '{ RussianStressConverter, splitSentences, textToSsmlRuSimple }', TTS);

const stress = new RussianStressConverter();
stress.loadDictionary();

function escXml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const [, , inFile, outFile] = process.argv;
const texts = JSON.parse(fs.readFileSync(inFile, 'utf-8'));
const out = texts.map(t => {
  let s = replaceNumbers(t).replace(/\s+/g, ' ').trim();
  s = stress.processText(s);
  return splitSentences(s).map(sent =>
    `<speak><prosody rate="medium" pitch="medium">${textToSsmlRuSimple(escXml(sent))}</prosody></speak>`);
});
fs.writeFileSync(outFile, JSON.stringify(out), 'utf-8');
