import test from 'node:test';
import assert from 'node:assert/strict';
import { buildYouTubeEmbedUrl, getYouTubeVideoId } from '../src/lib/youtubeLivePreview.js';

const videoId = 'dQw4w9WgXcQ';

test('extracts ids from supported YouTube URL formats', () => {
  for (const url of [
    `https://www.youtube.com/watch?v=${videoId}`,
    `https://youtu.be/${videoId}`,
    `https://www.youtube.com/live/${videoId}`,
    `https://www.youtube.com/shorts/${videoId}`,
    `https://www.youtube.com/embed/${videoId}`,
    `https://m.youtube.com/watch?v=${videoId}`,
  ]) {
    assert.equal(getYouTubeVideoId(url), videoId, url);
  }
});

test('rejects non-YouTube hosts, unsafe schemes, malformed ids and empty input', () => {
  for (const url of [
    `https://youtube.com.evil.com/watch?v=${videoId}`,
    `https://notyoutube.com/watch?v=${videoId}`,
    `javascript://youtube.com/watch?v=${videoId}`,
    'https://www.youtube.com/live',
    'https://www.youtube.com/watch?v=short',
    '',
    null,
    42,
  ]) {
    assert.equal(getYouTubeVideoId(url), null, String(url));
  }
});

test('builds only the official embed URL without a quality override', () => {
  const url = buildYouTubeEmbedUrl(videoId);
  assert.equal(url, `https://www.youtube.com/embed/${videoId}?playsinline=1&rel=0`);
  assert.equal(url.includes('vq='), false);
  assert.equal(buildYouTubeEmbedUrl('invalid'), null);
});
