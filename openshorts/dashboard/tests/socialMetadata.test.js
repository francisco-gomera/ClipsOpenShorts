import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSocialPostMetadata, metadataDraftFromClip } from '../src/lib/socialMetadata.js';

test('each clip initializes its own platform copy and legacy clips stay editable', () => {
  const first = metadataDraftFromClip({
    video_title_for_youtube_short: 'Title A',
    video_description_for_tiktok: 'TikTok A',
    video_description_for_instagram: 'Instagram A',
    video_description_for_youtube_short: 'YouTube A',
  });
  const legacy = metadataDraftFromClip({ video_description_for_tiktok: 'Old TikTok' });

  assert.deepEqual(first, { youtubeTitle: 'Title A', tiktokDescription: 'TikTok A',
    instagramDescription: 'Instagram A', youtubeDescription: 'YouTube A' });
  assert.deepEqual(legacy, { youtubeTitle: 'Viral Short', tiktokDescription: 'Old TikTok',
    instagramDescription: '', youtubeDescription: '' });
  assert.notEqual(metadataDraftFromClip({ video_description_for_tiktok: 'B' }).tiktokDescription,
    first.tiktokDescription);
});

test('publication payload keeps platform descriptions and YouTube title independent', () => {
  const payload = buildSocialPostMetadata({ youtubeTitle: 'YT title',
    tiktokDescription: 'TikTok edited', instagramDescription: 'Instagram edited',
    youtubeDescription: 'YouTube edited' });

  assert.equal(payload.tiktok_description, 'TikTok edited');
  assert.equal(payload.instagram_description, 'Instagram edited');
  assert.equal(payload.youtube_title, 'YT title');
  assert.equal(payload.youtube_description, 'YouTube edited');
  assert.equal(payload.description, 'TikTok edited');
});
