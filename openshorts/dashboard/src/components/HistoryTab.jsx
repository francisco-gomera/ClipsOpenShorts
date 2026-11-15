import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Loader2,
  Download,
  Film,
  FolderOpen,
  Trash2,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Video,
  RefreshCw
} from 'lucide-react';
import { apiJson } from '../lib/api';

/**
 * Gallery / History of projects and generated clips.
 * Supports both self-host (local filesystem via /api/projects)
 * and cloud mode (R2/Postgres via /api/history + /api/projects).
 */
export default function HistoryTab({ onReopenProject }) {
  const [loading, setLoading] = useState(true);
  const [projectsList, setProjectsList] = useState([]);
  const [cloudVideos, setCloudVideos] = useState([]);
  const [reopening, setReopening] = useState(null);
  const [retrying, setRetrying] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const [reopenError, setReopenError] = useState('');
  const [error, setError] = useState('');

  const handleRetry = async (jobId) => {
    if (retrying) return;
    setRetrying(jobId);
    setError('');
    try {
      await apiJson(`/api/jobs/${jobId}/retry`, { method: 'POST' });
      if (onReopenProject) {
        await onReopenProject(jobId);
      } else {
        await loadData();
      }
    } catch (e) {
      setError('Could not retry project from intermediate stage.');
    } finally {
      setRetrying(null);
    }
  };

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    let loadedAny = false;

    // 1. Load /api/projects (works for both self-host and cloud)
    try {
      const pData = await apiJson('/api/projects');
      if (pData && Array.isArray(pData.projects)) {
        setProjectsList(pData.projects);
        loadedAny = true;
      }
    } catch {
      // Ignore if not available
    }

    // 2. Load /api/history (cloud mode with Clerk & Postgres)
    try {
      const hData = await apiJson('/api/history');
      if (hData && Array.isArray(hData.videos)) {
        setCloudVideos(hData.videos);
        loadedAny = true;
      }
    } catch {
      // Normal 404/401 in self-host mode
    }

    if (!loadedAny) {
      setError('Could not load projects. Please ensure the backend is running.');
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleReopen = async (jobId) => {
    if (!onReopenProject || reopening) return;
    setReopening(jobId);
    setReopenError('');
    try {
      await onReopenProject(jobId);
    } catch (e) {
      setReopenError('Could not reopen this project. Please try again.');
      setReopening(null);
    }
  };

  const handleDelete = async (jobId) => {
    if (deleting) return;
    setDeleting(jobId);
    try {
      await apiJson(`/api/projects/${jobId}`, { method: 'DELETE' });
      setProjectsList((prev) => prev.filter((p) => p.job_id !== jobId));
      setCloudVideos((prev) => prev.filter((v) => (v.job_id || v.id) !== jobId));
      setConfirmDeleteId(null);
    } catch (e) {
      setError('Could not delete project. It may be currently processing.');
    } finally {
      setDeleting(null);
    }
  };

  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }) : '');

  // Render status badge for a project
  const renderStatusBadge = (status) => {
    switch (status) {
      case 'completed':
      case 'complete':
        return (
          <span className="inline-flex items-center gap-1 text-micro font-mono uppercase px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <CheckCircle2 size={12} /> Completed
          </span>
        );
      case 'processing':
        return (
          <span className="inline-flex items-center gap-1 text-micro font-mono uppercase px-2 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20">
            <Loader2 size={12} className="animate-spin" /> Processing
          </span>
        );
      case 'queued':
        return (
          <span className="inline-flex items-center gap-1 text-micro font-mono uppercase px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <Clock size={12} /> Queued
          </span>
        );
      case 'interrupted':
        return (
          <span className="inline-flex items-center gap-1 text-micro font-mono uppercase px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <AlertTriangle size={12} /> Interrupted
          </span>
        );
      case 'partially_recoverable':
      case 'recoverable':
        return (
          <span className="inline-flex items-center gap-1 text-micro font-mono uppercase px-2 py-0.5 rounded bg-violet-500/10 text-violet-400 border border-violet-500/20">
            <RefreshCw size={12} /> Recoverable
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1 text-micro font-mono uppercase px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20">
            <AlertTriangle size={12} /> Failed
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 text-micro font-mono uppercase px-2 py-0.5 rounded bg-white/5 text-muted border border-rule">
            {status || 'Unknown'}
          </span>
        );
    }
  };

  // Merge projects from /api/projects with videos from /api/history (cloud)
  const unifiedProjects = useMemo(() => {
    const map = new Map();

    // First populate from /api/projects
    for (const p of projectsList) {
      map.set(p.job_id, {
        job_id: p.job_id,
        title: p.title || `Project ${p.job_id.slice(0, 8)}`,
        created_at: p.created_at,
        updated_at: p.updated_at,
        status: p.status || 'completed',
        has_source: Boolean(p.has_source),
        source_file: p.source_file,
        source_duration: p.source_duration,
        clips: p.clips || [],
        last_error: p.last_error,
      });
    }

    // Merge in any cloud videos from /api/history
    for (const v of cloudVideos) {
      const jobId = v.job_id || v.id;
      if (!map.has(jobId)) {
        map.set(jobId, {
          job_id: jobId,
          title: v.title || `Project ${jobId.slice(0, 8)}`,
          created_at: v.created_at,
          status: 'completed',
          has_source: false,
          clips: [],
          last_error: null,
        });
      }
      const existing = map.get(jobId);
      // If project has no local clips, convert cloud video to a clip representation
      if (!existing.clips.some((c) => c.video_url === v.view_url || c.id === v.id)) {
        existing.clips.push({
          index: existing.clips.length,
          title: v.title || `Clip ${existing.clips.length + 1}`,
          video_url: v.view_url,
          download_url: v.download_url,
          available: true,
          created_at: v.created_at,
        });
      }
    }

    return Array.from(map.values()).sort(
      (a, b) => new Date(b.created_at || b.updated_at || 0) - new Date(a.created_at || a.updated_at || 0)
    );
  }, [projectsList, cloudVideos]);

  if (loading && unifiedProjects.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-muted">
        <Loader2 className="animate-spin text-brass mb-3" size={32} />
        <p className="text-sm">Loading projects…</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 md:p-8 max-w-6xl mx-auto animate-fade">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-2">
        <div>
          <p className="eyebrow mb-1">02 · PROJECTS</p>
          <h1 className="font-display lowercase text-2xl sm:text-3xl text-ink">Project Gallery</h1>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="btn-ghost px-3 py-1.5 text-xs flex items-center gap-1.5"
          title="Refresh project list"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      <p className="text-muted text-sm mb-8 lowercase">
        Browse previously processed videos and generated shorts. Reopen any project to edit clips or continue where you left off.
      </p>

      {error && (
        <div className="p-3 mb-6 rounded bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm">
          {error}
        </div>
      )}

      {reopenError && (
        <div className="p-3 mb-6 rounded bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm">
          {reopenError}
        </div>
      )}

      {unifiedProjects.length === 0 ? (
        <div className="text-center py-20 text-muted card p-10">
          <Film size={44} className="mx-auto mb-4 text-muted/60" />
          <h3 className="text-ink font-medium text-base mb-1">No projects found</h3>
          <p className="text-sm lowercase">
            Create your first short from the Clip Generator tab to see it here.
          </p>
        </div>
      ) : (
        <div className="space-y-10">
          {unifiedProjects.map((project) => {
            const hasClips = project.clips && project.clips.length > 0;
            const availableClips = project.clips.filter((c) => c.available !== false);

            return (
              <section
                key={project.job_id}
                className="card p-5 sm:p-6 transition-all hover:border-rule-strong"
              >
                {/* Project Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-rule">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2.5">
                      <h2
                        className="text-base sm:text-lg text-ink font-medium truncate"
                        title={project.title}
                      >
                        {project.title}
                      </h2>
                      {renderStatusBadge(project.status)}
                      {project.has_source && (
                        <span className="inline-flex items-center gap-1 text-micro font-mono uppercase px-2 py-0.5 rounded bg-white/5 text-ink/70 border border-rule">
                          <Video size={11} /> Source available
                        </span>
                      )}
                    </div>
                    <p className="readout text-xs">
                      {fmtDate(project.created_at || project.updated_at)} · {availableClips.length} {availableClips.length === 1 ? 'clip' : 'clips'}
                      {project.source_duration ? ` · ${Math.round(project.source_duration)}s source` : ''}
                      <span className="font-mono text-muted/70 ml-2">({project.job_id.slice(0, 8)})</span>
                    </p>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 shrink-0">
                    {['interrupted', 'failed', 'partially_recoverable', 'recoverable'].includes(project.status) && (
                      <button
                        onClick={() => handleRetry(project.job_id)}
                        disabled={Boolean(retrying)}
                        className="btn-ghost px-3 py-1.5 text-xs flex items-center gap-1.5 text-amber-400 hover:text-amber-300"
                        title="Resume processing from the last valid stage"
                      >
                        {retrying === project.job_id ? (
                          <>
                            <Loader2 size={13} className="animate-spin" /> Retrying…
                          </>
                        ) : (
                          <>
                            <RefreshCw size={13} /> Retry Stage
                          </>
                        )}
                      </button>
                    )}

                    {onReopenProject && (
                      <button
                        onClick={() => handleReopen(project.job_id)}
                        disabled={Boolean(reopening)}
                        className="btn-primary px-3 py-1.5 text-xs flex items-center gap-1.5"
                        title="Open this project in the Clip Generator to edit or review"
                      >
                        {reopening === project.job_id ? (
                          <>
                            <Loader2 size={13} className="animate-spin" /> Reopening…
                          </>
                        ) : (
                          <>
                            <FolderOpen size={13} /> Open Project
                          </>
                        )}
                      </button>
                    )}

                    {/* Delete confirmation */}
                    {confirmDeleteId === project.job_id ? (
                      <div className="flex items-center gap-1.5 bg-rose-500/10 px-2 py-1 rounded border border-rose-500/20">
                        <span className="text-xs text-rose-400 font-medium">Delete?</span>
                        <button
                          onClick={() => handleDelete(project.job_id)}
                          disabled={deleting === project.job_id}
                          className="px-2 py-0.5 text-xs bg-rose-600 text-white rounded hover:bg-rose-500 transition-colors"
                        >
                          {deleting === project.job_id ? <Loader2 size={12} className="animate-spin" /> : 'Yes'}
                        </button>
                        <button
                          onClick={() => setConfirmDeleteId(null)}
                          className="px-2 py-0.5 text-xs text-muted hover:text-ink transition-colors"
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDeleteId(project.job_id)}
                        disabled={Boolean(deleting)}
                        className="btn-ghost px-2.5 py-1.5 text-xs text-muted hover:text-rose-400"
                        title="Delete project and free disk space"
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                </div>

                {/* Optional error message on failed/interrupted project */}
                {project.last_error && (
                  <div className="mt-3 p-2.5 rounded bg-amber-500/5 border border-amber-500/15 text-xs text-amber-300">
                    <span className="font-semibold">Status note: </span>
                    {project.last_error}
                  </div>
                )}

                {/* Clips Grid */}
                <div className="mt-5">
                  {!hasClips || availableClips.length === 0 ? (
                    <div className="py-6 text-center text-muted text-xs lowercase">
                      No rendered clips available for this project yet.
                      {project.status === 'interrupted' || project.status === 'recoverable' ? (
                        <span className="block mt-1 text-ink/70">
                          Reopen the project to resume processing.
                        </span>
                      ) : null}
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                      {availableClips.map((clip) => {
                        const clipTitle =
                          clip.video_title_for_youtube_short ||
                          clip.title ||
                          `Clip #${clip.index + 1}`;
                        const mediaUrl = clip.video_url;
                        const dlUrl = clip.download_url || clip.video_url;

                        return (
                          <div
                            key={clip.index ?? clip.id ?? clip.video_url}
                            className="card card-hover overflow-hidden group flex flex-col justify-between bg-black/40 border-rule/60"
                          >
                            <div className="aspect-[9/16] bg-black relative flex items-center justify-center overflow-hidden">
                              {mediaUrl ? (
                                <video
                                  src={mediaUrl}
                                  controls
                                  preload="metadata"
                                  className="w-full h-full object-contain"
                                />
                              ) : (
                                <Film size={32} className="text-muted/40" />
                              )}
                            </div>
                            <div className="p-3">
                              <p
                                className="text-xs text-ink font-medium line-clamp-2 mb-2"
                                title={clipTitle}
                              >
                                {clipTitle}
                              </p>
                              <div className="flex items-center justify-between pt-1 border-t border-rule/40">
                                <span className="readout text-micro">
                                  {clip.duration ? `${Math.round(clip.duration)}s` : `Clip #${clip.index + 1}`}
                                </span>
                                {dlUrl && (
                                  <a
                                    href={dlUrl}
                                    download
                                    className="text-micro font-mono uppercase text-brass hover:text-ink flex items-center gap-1 transition-colors"
                                    title="Download clip"
                                  >
                                    <Download size={12} /> Save
                                  </a>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
