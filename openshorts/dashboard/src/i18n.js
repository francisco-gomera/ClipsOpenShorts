/**
 * MyClipper — Traducciones al español (ES)
 * Uso: import { t } from './i18n'; → t('generate_clips')
 * Para añadir un idioma: añade una sección nueva y cambia LANG.
 */

const LANG = 'es';

const translations = {
  es: {
    // ── Navegación ──────────────────────────────────────────────────────────
    nav_dashboard:        'Inicio',
    nav_projects:         'Proyectos',
    nav_settings:         'Ajustes',
    nav_history:          'Historial',
    nav_back_to_app:      '← Volver',
    open_app:             'Abrir app',
    get_started:          'Comenzar',
    log_in:               'Iniciar sesión',

    // ── Pantalla principal / MediaInput ──────────────────────────────────────
    upload_file:          'Subir archivo',
    video_url:            'URL de vídeo',
    paste_link:           'https://... pega un enlace de vídeo',
    supported_platforms:  'Pega un enlace de',
    more_sites:           '…y más de 1.000 sitios. Si un enlace tiene un vídeo público, generalmente podemos procesarlo.',
    click_to_upload:      'Haz clic para subir o arrastra el archivo aquí',
    file_hint:            'MP4, MOV hasta 500 MB · mínimo {min}s de duración',
    remove_file:          'Eliminar y elegir otro',
    video_identified:     'Vídeo identificado',
    open_source_link:     'Abrir enlace de origen',
    output_format:        'Formato de salida',
    shorts_reels_tiktok:  'Shorts · Reels · TikTok',
    feed_posts:           'Posts en feed',
    keep_landscape:       'Mantener horizontal · YouTube',
    advanced_options:     'opciones avanzadas',
    clips_to_aim:         'clips objetivo',
    min_length:           'duración mín. (s)',
    max_length:           'duración máx. (s)',
    targets_not_guarantees: 'Objetivos, no garantías: la IA devuelve menos clips si el material no los tiene. Deja en blanco para que decida automáticamente.',
    vertical_layout:      'diseño vertical',
    layout_auto:          'Auto (la IA elige por vídeo)',
    layout_split:         'Dos personas apiladas',
    layout_screencast:    'Pantalla sobre presentador',
    layout_none:          'Recorte único',
    auto_hook_label:      'títulos de gancho automáticos en clips',
    hook_change_hint:     'Puedes cambiar el texto del gancho, estilo, posición y tamaño de cada clip después con su botón.',
    hook_style_classic:   'Clásico',
    hook_style_pill:      'Píldoras',
    hook_style_dark:      'Oscuro',
    hook_style_yellow:    'Amarillo',
    hook_style_red:       'Rojo',
    hook_style_outline:   'Contorno',
    hook_style_outline_plus: 'Contorno+',
    rights_disclaimer:    'Confirmo que soy dueño de este contenido o tengo derechos para procesarlo. Soy responsable de cualquier contenido que envíe. Ver nuestros',
    terms:                'Términos',
    and:                  'y',
    privacy_policy:       'Política de privacidad',
    generate_clips:       'Generar clips',
    processing_video:     'Procesando vídeo…',
    file_too_short:       'Este vídeo dura {dur}s. La generación de clips necesita al menos {min}s de grabación para recortar: ya es un clip corto. Elige un vídeo más largo.',

    // ── Procesamiento ────────────────────────────────────────────────────────
    processing:           'Procesando',
    processing_title:     'Generando clips',
    stage_pending:        'Pendiente',
    stage_running:        'En progreso',
    stage_done:           'Completado',
    stage_failed:         'Error',
    stage_skipped:        'Omitido',
    stage_waiting:        'Esperando…',
    retry_stage:          'Reintentar desde esta etapa',
    cancel:               'Cancelar',
    system_logs:          'Registros del sistema',
    no_logs:              'Sin registros aún',
    waiting_rate_limit:   'Esperando límite de Gemini',
    retry_in:             'Reintentar en',
    elapsed:              'Transcurrido',
    estimated:            'Estimado',
    stage_of:             'Etapa {current} de {total}',
    trimming:             'Recortando',
    reframing:            'Reencuadrando',
    hook:                 'Gancho',
    subtitles:            'Subtítulos',
    analyzing:            'Analizando momentos del vídeo…',
    clips_ready:          'Clips listos',
    clip_in_progress:     'Clip en proceso',

    // ── Resultados ───────────────────────────────────────────────────────────
    results_title:        'Clips generados',
    no_results:           'No se generaron clips',
    download:             'Descargar',
    download_all:         'Descargar todos',
    edit:                 'Editar',
    reframe:              'Reencuadrar',
    share:                'Compartir',
    hook_btn:             'Gancho',
    subtitle_btn:         'Subtítulos',
    watermark_btn:        'Marca de agua',
    translate_btn:        'Traducir',
    duration:             'Duración',
    score:                'Puntuación',
    new_job:              'Nuevo vídeo',
    back:                 'Volver',

    // ── Proyectos / Galería ──────────────────────────────────────────────────
    projects:             'Proyectos',
    recent_projects:      'Proyectos recientes',
    no_projects:          'Sin proyectos aún',
    no_projects_hint:     'Cuando generes tus primeros clips, aparecerán aquí.',
    open_project:         'Abrir',
    delete_project:       'Eliminar',
    delete_confirm:       '¿Eliminar este proyecto?',
    delete_confirm_hint:  'Se eliminarán todos los clips y el vídeo original. Esta acción no se puede deshacer.',
    confirm_delete:       'Sí, eliminar',
    cancel_delete:        'Cancelar',
    project_failed:       'Fallido',
    project_processing:   'Procesando',
    project_completed:    'Completado',
    clips_count:          '{n} clips',
    original_unavailable: 'Original no disponible',

    // ── Ajustes ──────────────────────────────────────────────────────────────
    settings:             'Ajustes',
    api_keys:             'Claves API',
    gemini_key:           'Clave de Gemini',
    elevenlabs_key:       'Clave de ElevenLabs',
    fal_key:              'Clave de fal.ai',
    upload_post_key:      'Clave de Upload-Post',
    save:                 'Guardar',
    saved:                'Guardado',
    key_placeholder:      'Pega tu clave aquí',

    // ── Errores y estados vacíos ─────────────────────────────────────────────
    error_generic:        'Algo ha ido mal',
    error_retry:          'Reintentar',
    error_404:            'No encontrado',
    loading:              'Cargando…',
    signing_in:           'iniciando sesión…',

    // ── Auth / cuenta ────────────────────────────────────────────────────────
    account_deleted:      'Tu cuenta ha sido eliminada',
    account_deleted_desc: 'Tus proyectos, clips y transcripciones han desaparecido, cualquier suscripción está cancelada y tus claves API ya no funcionan. Te hemos enviado una confirmación por correo.',
    account_deleted_hint: 'Puedes volver cuando quieras: registrarte de nuevo con la misma dirección crea una cuenta nueva y vacía.',
    back_to_app:          'Volver a {name}',

    // ── Misc ─────────────────────────────────────────────────────────────────
    github:               'GitHub',
    star_on_github:       'Dale una estrella en GitHub',
    mcp_connect:          'Conectar MCP',
    source_too_short_warn:'Vídeo demasiado corto',
  },
};

/**
 * Devuelve la traducción de `key` interpolando `{var}` con los valores de `vars`.
 * Si no existe la clave, devuelve la clave en sí (safe fallback).
 */
export function t(key, vars = {}) {
  const str = translations[LANG]?.[key] ?? key;
  return str.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? `{${k}}`);
}

export default t;
