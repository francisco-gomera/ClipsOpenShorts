export function metadataDraftFromClip(clip = {}) {
  return {
    youtubeTitle: clip.video_title_for_youtube_short || 'Viral Short',
    tiktokDescription: clip.video_description_for_tiktok || '',
    instagramDescription: clip.video_description_for_instagram || '',
    youtubeDescription: clip.video_description_for_youtube_short || '',
  };
}

export function buildSocialPostMetadata(draft = {}) {
  return {
    title: draft.youtubeTitle || 'Viral Short',
    // Legacy clients receive one best-effort caption; modern servers use the
    // four explicit fields below and never share this value across platforms.
    description: draft.tiktokDescription || draft.instagramDescription || draft.youtubeDescription || '',
    tiktok_description: draft.tiktokDescription || '',
    instagram_description: draft.instagramDescription || '',
    youtube_title: draft.youtubeTitle || 'Viral Short',
    youtube_description: draft.youtubeDescription || '',
  };
}
