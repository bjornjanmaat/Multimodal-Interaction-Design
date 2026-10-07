#!/usr/bin/env node
/**
 * Standalone Klattsch Formant TTS helper.
 * Takes English text and an output WAV path.
 * Usage: node klattsch_tts.js "Text to speak" [output.wav]
 */
const fs = require('fs');
const path = require('path');

let klattsch;
let textToPhonemes;

try {
  klattsch = require('klattsch');
  const pkgPath = require.resolve('klattsch/package.json');
  const dir = path.dirname(pkgPath);
  const pronounceModule = require(path.join(dir, 'src', 'engine', 'pronounce.js'));
  textToPhonemes = pronounceModule.textToPhonemes;
} catch (e) {
  console.error('Failed to load klattsch engine:', e.message);
  process.exit(1);
}

const text = process.argv[2] || '';
const outPath = process.argv[3] || '/tmp/klattsch_out.wav';

if (!text.trim()) {
  process.exit(0);
}

try {
  // Convert English words to ARPABET phonemes
  const phones = textToPhonemes(text);
  if (!phones || !phones.length) {
    console.error('No phonemes extracted from text');
    process.exit(1);
  }

  // Add slight rhythm / pitch bounce for hip-hop delivery
  const phonemeStr = phones.map(p => p.code).join(' ');

  const { voices, totalMs } = klattsch.compileString(phonemeStr);
  const sampleRate = 48000;
  const buf = new Float32Array(Math.ceil((totalMs * sampleRate) / 1000));

  for (const v of voices) {
    if (!v.schedule || !v.schedule.length) continue;
    const vb = klattsch.renderToBuffer({ sampleRate, schedule: v.schedule, totalMs: v.totalMs });
    const n = Math.min(buf.length, vb.length);
    for (let i = 0; i < n; i++) {
      buf[i] += vb[i];
    }
  }

  const { bytes } = klattsch.encodeWav(buf, sampleRate, { peakNormalize: 0.95 });
  fs.writeFileSync(outPath, Buffer.from(bytes));
  console.log(`OK: wrote ${outPath} (${(totalMs / 1000).toFixed(2)}s)`);
} catch (err) {
  console.error('Error during synthesis:', err);
  process.exit(1);
}
