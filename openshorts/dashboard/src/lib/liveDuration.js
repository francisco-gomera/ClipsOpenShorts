const MIN_SECONDS = 10;
const MAX_SECONDS = 240;

export function validateLiveDuration(minValue, maxValue) {
  const parse = (value) => {
    if (typeof value === 'string' && !/^\d+$/.test(value)) return null;
    const number = Number(value);
    return Number.isInteger(number) ? number : null;
  };
  const min = parse(minValue);
  const max = parse(maxValue);

  if (min == null || max == null) {
    return { min, max, error: 'Introduce ambas duraciones como números enteros.' };
  }
  if (min < MIN_SECONDS || min > MAX_SECONDS) {
    return { min, max, error: `La duración mínima debe estar entre ${MIN_SECONDS} y ${MAX_SECONDS} segundos.` };
  }
  if (max < MIN_SECONDS || max > MAX_SECONDS) {
    return { min, max, error: `La duración máxima debe estar entre ${MIN_SECONDS} y ${MAX_SECONDS} segundos.` };
  }
  if (min > max) {
    return { min, max, error: 'La duración mínima no puede superar a la máxima.' };
  }
  return { min, max, error: '' };
}

export function buildLiveCreatePayload(url, minValue, maxValue) {
  const { min, max, error } = validateLiveDuration(minValue, maxValue);
  if (error) throw new Error(error);
  return { url: String(url || '').trim(), min_clip_seconds: min, max_clip_seconds: max };
}
