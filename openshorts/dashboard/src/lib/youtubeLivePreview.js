const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;

export function getYouTubeVideoId(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol)) return null;
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    if (host !== 'youtu.be' && host !== 'youtube.com' && !host.endsWith('.youtube.com')) return null;

    let id = '';
    if (host === 'youtu.be') {
      id = url.pathname.split('/').filter(Boolean)[0] || '';
    } else if (url.pathname === '/watch') {
      id = url.searchParams.get('v') || '';
    } else {
      const match = url.pathname.match(/^\/(?:live|shorts|embed)\/([^/?#]+)/);
      id = match?.[1] || '';
    }
    return VIDEO_ID.test(id) ? id : null;
  } catch (_) {
    return null;
  }
}

export function buildYouTubeEmbedUrl(videoId) {
  return VIDEO_ID.test(String(videoId || ''))
    ? `https://www.youtube.com/embed/${videoId}?playsinline=1&rel=0`
    : null;
}
