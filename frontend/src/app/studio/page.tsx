'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Divider,
  FileButton,
  Group,
  Loader,
  Progress,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import {
  IconArrowLeft,
  IconCheck,
  IconDownload,
  IconEdit,
  IconPlayerPlay,
  IconRefresh,
  IconTrash,
  IconUpload,
  IconVideo,
  IconWand,
} from '@tabler/icons-react';

const API = '/api/proxy';

const glass = {
  background: 'rgba(255,255,255,0.04)',
  backdropFilter: 'blur(8px)',
  border: '1px solid rgba(255,255,255,0.10)',
  borderRadius: '16px',
};

const accent = '#00FFC8';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Word {
  word: string;
  start: number;
  end: number;
  probability: number;
}

interface Segment {
  id: number;
  start: number;
  end: number;
  text: string;
  words: Word[];
}

interface Transcript {
  segments: Segment[];
  language: string;
  duration: number | null;
}

interface StudioJob {
  id: string;
  status: 'uploaded' | 'transcribing' | 'transcribed' | 'exporting' | 'done' | 'error';
  filename: string;
  video_path: string;
  transcript: Transcript | null;
  export_path: string | null;
  export_filename: string | null;
  created_at: number;
  updated_at: number;
  error: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtTime(s: number) {
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(1);
  return `${m}:${sec.padStart(4, '0')}`;
}

function statusColor(status: StudioJob['status']) {
  const map: Record<string, string> = {
    uploaded: 'blue',
    transcribing: 'yellow',
    transcribed: 'teal',
    exporting: 'orange',
    done: 'green',
    error: 'red',
  };
  return map[status] ?? 'gray';
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function StudioPage() {
  const [jobs, setJobs] = useState<StudioJob[]>([]);
  const [activeJob, setActiveJob] = useState<StudioJob | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [whisperModel, setWhisperModel] = useState('base');
  const [editedSegments, setEditedSegments] = useState<Segment[]>([]);
  const [exportSettings, setExportSettings] = useState({
    crop_to_vertical: true,
    words_per_chunk: 3,
    font_size: 22,
    highlight_color: '&H0000CFFF',
    font_name: 'Arial',
  });
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  // Load jobs on mount
  useEffect(() => {
    fetchJobs();
  }, []);

  // Poll active job while processing
  useEffect(() => {
    if (activeJob && ['transcribing', 'exporting'].includes(activeJob.status)) {
      pollRef.current = setInterval(() => pollJob(activeJob.id), 2000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [activeJob?.id, activeJob?.status]);

  // Sync edited segments when transcript loads
  useEffect(() => {
    if (activeJob?.transcript) {
      setEditedSegments(activeJob.transcript.segments);
    }
  }, [activeJob?.transcript]);

  async function fetchJobs() {
    const res = await fetch(`${API}/studio/jobs`);
    if (res.ok) {
      const data = await res.json();
      setJobs(data.jobs);
    }
  }

  async function pollJob(jobId: string) {
    const res = await fetch(`${API}/studio/jobs/${jobId}`);
    if (res.ok) {
      const job: StudioJob = await res.json();
      setActiveJob(job);
      setJobs(prev => prev.map(j => j.id === job.id ? job : j));
      if (!['transcribing', 'exporting'].includes(job.status)) {
        if (pollRef.current) clearInterval(pollRef.current);
      }
    }
  }

  const handleUpload = useCallback(async (file: File | null) => {
    if (!file) return;
    setUploading(true);
    setUploadProgress(0);

    const form = new FormData();
    form.append('file', file);

    // Use XHR for upload progress
    await new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) setUploadProgress(Math.round(e.loaded / e.total * 100));
      };
      xhr.onload = async () => {
        if (xhr.status === 200) {
          const data = JSON.parse(xhr.responseText);
          await fetchJobs();
          const jobRes = await fetch(`${API}/studio/jobs/${data.job_id}`);
          if (jobRes.ok) {
            const job = await jobRes.json();
            setActiveJob(job);
          }
          resolve();
        } else {
          reject(new Error(xhr.responseText));
        }
      };
      xhr.onerror = () => reject(new Error('Upload failed'));
      xhr.open('POST', `${API}/studio/upload`);
      xhr.send(form);
    });

    setUploading(false);
    setUploadProgress(0);
  }, []);

  async function handleTranscribe() {
    if (!activeJob) return;
    await fetch(`${API}/studio/transcribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: activeJob.id, model: whisperModel }),
    });
    pollJob(activeJob.id);
  }

  async function handleSaveTranscript() {
    if (!activeJob) return;
    const transcript = { ...activeJob.transcript!, segments: editedSegments };
    await fetch(`${API}/studio/transcript/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: activeJob.id, transcript }),
    });
  }

  async function handleExport() {
    if (!activeJob) return;
    await handleSaveTranscript();
    await fetch(`${API}/studio/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: activeJob.id, ...exportSettings }),
    });
    pollJob(activeJob.id);
  }

  async function handleDelete(jobId: string) {
    await fetch(`${API}/studio/jobs/${jobId}`, { method: 'DELETE' });
    if (activeJob?.id === jobId) setActiveJob(null);
    fetchJobs();
  }

  function updateSegmentText(segId: number, text: string) {
    setEditedSegments(prev =>
      prev.map(s => s.id === segId ? { ...s, text } : s)
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Box p="xl" style={{ minHeight: '100vh', background: '#0a0a0f' }}>
      {/* Header */}
      <Group mb="xl">
        <ActionIcon component={Link} href="/" variant="subtle" color="gray" size="lg">
          <IconArrowLeft size={18} />
        </ActionIcon>
        <Box>
          <Title order={2} style={{ color: accent }}>Studio</Title>
          <Text size="sm" c="dimmed">Video → Captions → Export</Text>
        </Box>
      </Group>

      <Group align="flex-start" gap="xl" style={{ flexWrap: 'nowrap' }}>

        {/* ── LEFT: Job list + upload ───────────────────────────────────── */}
        <Stack style={{ width: 280, flexShrink: 0 }}>
          <Card style={glass} p="md">
            <Text fw={600} mb="sm" size="sm">Upload Video</Text>
            {uploading ? (
              <Stack gap="xs">
                <Progress value={uploadProgress} color="teal" animated />
                <Text size="xs" c="dimmed" ta="center">{uploadProgress}% uploaded</Text>
              </Stack>
            ) : (
              <FileButton onChange={handleUpload} accept="video/*">
                {(props) => (
                  <Button
                    {...props}
                    fullWidth
                    leftSection={<IconUpload size={16} />}
                    variant="light"
                    color="teal"
                  >
                    Choose Video
                  </Button>
                )}
              </FileButton>
            )}
            <Text size="xs" c="dimmed" mt="xs" ta="center">MP4, MOV, AVI, WebM · max 500MB</Text>
          </Card>

          {/* Job list */}
          <Stack gap="xs">
            <Group justify="space-between">
              <Text size="sm" fw={600} c="dimmed">JOBS</Text>
              <ActionIcon size="sm" variant="subtle" onClick={fetchJobs}>
                <IconRefresh size={14} />
              </ActionIcon>
            </Group>
            {jobs.length === 0 && (
              <Text size="xs" c="dimmed" ta="center" mt="md">No jobs yet</Text>
            )}
            {jobs.map(job => (
              <Card
                key={job.id}
                style={{
                  ...glass,
                  cursor: 'pointer',
                  border: activeJob?.id === job.id
                    ? `1px solid ${accent}`
                    : '1px solid rgba(255,255,255,0.10)',
                }}
                p="sm"
                onClick={() => {
                  setActiveJob(job);
                  if (job.transcript) setEditedSegments(job.transcript.segments);
                }}
              >
                <Group justify="space-between" wrap="nowrap">
                  <Box style={{ minWidth: 0 }}>
                    <Text size="xs" fw={600} truncate>
                      {job.filename || job.id}
                    </Text>
                    <Badge size="xs" color={statusColor(job.status)} mt={2}>
                      {job.status}
                    </Badge>
                  </Box>
                  <ActionIcon
                    size="sm"
                    variant="subtle"
                    color="red"
                    onClick={(e) => { e.stopPropagation(); handleDelete(job.id); }}
                  >
                    <IconTrash size={13} />
                  </ActionIcon>
                </Group>
              </Card>
            ))}
          </Stack>
        </Stack>

        {/* ── RIGHT: Editor ─────────────────────────────────────────────── */}
        {!activeJob ? (
          <Center style={{ flex: 1, height: 400 }}>
            <Stack align="center" gap="sm">
              <IconVideo size={48} color="rgba(255,255,255,0.15)" />
              <Text c="dimmed">Upload a video to get started</Text>
            </Stack>
          </Center>
        ) : (
          <Stack style={{ flex: 1, minWidth: 0 }} gap="lg">

            {/* Job header */}
            <Card style={glass} p="md">
              <Group justify="space-between">
                <Box>
                  <Text fw={700}>{activeJob.filename}</Text>
                  <Group gap="xs" mt={4}>
                    <Badge color={statusColor(activeJob.status)}>{activeJob.status}</Badge>
                    {activeJob.transcript?.language && (
                      <Badge variant="outline" color="gray">
                        lang: {activeJob.transcript.language}
                      </Badge>
                    )}
                    {activeJob.transcript?.duration && (
                      <Badge variant="outline" color="gray">
                        {fmtTime(activeJob.transcript.duration)}
                      </Badge>
                    )}
                  </Group>
                </Box>
                {activeJob.status === 'error' && (
                  <Text size="xs" c="red">{activeJob.error}</Text>
                )}
              </Group>
            </Card>

            {/* Step 1: Transcribe */}
            {['uploaded', 'error'].includes(activeJob.status) && (
              <Card style={glass} p="md">
                <Text fw={600} mb="sm">Step 1 — Transcribe</Text>
                <Group>
                  <Select
                    label="Whisper model"
                    value={whisperModel}
                    onChange={(v) => setWhisperModel(v || 'base')}
                    data={[
                      { value: 'tiny', label: 'Tiny (fastest, less accurate)' },
                      { value: 'base', label: 'Base (recommended)' },
                      { value: 'small', label: 'Small (better accuracy)' },
                      { value: 'medium', label: 'Medium (best accuracy, slow)' },
                    ]}
                    size="sm"
                    style={{ width: 260 }}
                  />
                  <Button
                    mt={24}
                    leftSection={<IconWand size={16} />}
                    color="teal"
                    onClick={handleTranscribe}
                  >
                    Run Whisper
                  </Button>
                </Group>
              </Card>
            )}

            {/* Transcribing spinner */}
            {activeJob.status === 'transcribing' && (
              <Card style={glass} p="xl">
                <Center>
                  <Stack align="center" gap="sm">
                    <Loader color="teal" size="md" />
                    <Text c="dimmed">Transcribing with Whisper ({whisperModel})…</Text>
                    <Text size="xs" c="dimmed">This takes 1–3× the video duration on CPU</Text>
                  </Stack>
                </Center>
              </Card>
            )}

            {/* Step 2: Edit transcript */}
            {activeJob.transcript && ['transcribed', 'done', 'exporting'].includes(activeJob.status) && (
              <Card style={glass} p="md">
                <Group justify="space-between" mb="sm">
                  <Text fw={600}>Step 2 — Edit Captions</Text>
                  <Button
                    size="xs"
                    variant="light"
                    color="teal"
                    leftSection={<IconCheck size={13} />}
                    onClick={handleSaveTranscript}
                  >
                    Save edits
                  </Button>
                </Group>
                <Text size="xs" c="dimmed" mb="md">
                  Click any segment to edit the text. Word timestamps are preserved for caption sync.
                </Text>
                <Stack gap="xs" style={{ maxHeight: 360, overflowY: 'auto' }}>
                  {editedSegments.map((seg) => (
                    <Group key={seg.id} gap="sm" align="flex-start" wrap="nowrap">
                      <Text
                        size="xs"
                        c="dimmed"
                        style={{ width: 72, flexShrink: 0, paddingTop: 8, fontFamily: 'monospace' }}
                      >
                        {fmtTime(seg.start)}
                      </Text>
                      <Textarea
                        value={seg.text}
                        onChange={(e) => updateSegmentText(seg.id, e.target.value)}
                        autosize
                        minRows={1}
                        style={{ flex: 1 }}
                        styles={{
                          input: {
                            background: 'rgba(0,0,0,0.3)',
                            border: '1px solid rgba(255,255,255,0.08)',
                            fontSize: 13,
                          }
                        }}
                      />
                    </Group>
                  ))}
                </Stack>
              </Card>
            )}

            {/* Step 3: Export */}
            {activeJob.transcript && ['transcribed', 'done', 'error'].includes(activeJob.status) && (
              <Card style={glass} p="md">
                <Text fw={600} mb="sm">Step 3 — Export</Text>
                <Group align="flex-end" gap="md" wrap="wrap">
                  <Switch
                    label="Crop to 9:16 (Reels)"
                    checked={exportSettings.crop_to_vertical}
                    onChange={(e) => setExportSettings(s => ({ ...s, crop_to_vertical: e.currentTarget.checked }))}
                    color="teal"
                  />
                  <TextInput
                    label="Words per caption"
                    value={exportSettings.words_per_chunk}
                    onChange={(e) => setExportSettings(s => ({ ...s, words_per_chunk: parseInt(e.target.value) || 3 }))}
                    size="sm"
                    style={{ width: 140 }}
                    type="number"
                    min={1}
                    max={6}
                  />
                  <TextInput
                    label="Font size"
                    value={exportSettings.font_size}
                    onChange={(e) => setExportSettings(s => ({ ...s, font_size: parseInt(e.target.value) || 22 }))}
                    size="sm"
                    style={{ width: 100 }}
                    type="number"
                  />
                  <Select
                    label="Highlight color"
                    value={exportSettings.highlight_color}
                    onChange={(v) => setExportSettings(s => ({ ...s, highlight_color: v || '&H0000CFFF' }))}
                    data={[
                      { value: '&H0000CFFF', label: 'Yellow (viral)' },
                      { value: '&H00C8FF00', label: 'Green' },
                      { value: '&H00FF6B00', label: 'Orange' },
                      { value: '&H00FF00CF', label: 'Pink' },
                      { value: '&H00FFFFFF', label: 'White' },
                    ]}
                    size="sm"
                    style={{ width: 160 }}
                  />
                </Group>
                <Button
                  mt="md"
                  leftSection={<IconPlayerPlay size={16} />}
                  color="teal"
                  onClick={handleExport}
                  disabled={activeJob.status === 'exporting'}
                >
                  Burn Captions &amp; Export
                </Button>
              </Card>
            )}

            {/* Exporting spinner */}
            {activeJob.status === 'exporting' && (
              <Card style={glass} p="xl">
                <Center>
                  <Stack align="center" gap="sm">
                    <Loader color="orange" size="md" />
                    <Text c="dimmed">Burning captions with ffmpeg…</Text>
                  </Stack>
                </Center>
              </Card>
            )}

            {/* Done — download */}
            {activeJob.status === 'done' && activeJob.export_filename && (
              <Card style={{ ...glass, border: `1px solid ${accent}` }} p="md">
                <Group>
                  <IconCheck size={20} color={accent} />
                  <Box style={{ flex: 1 }}>
                    <Text fw={600} style={{ color: accent }}>Export ready!</Text>
                    <Text size="xs" c="dimmed">{activeJob.export_filename}</Text>
                  </Box>
                  <Button
                    component="a"
                    href={`/api/proxy/studio/exports/${activeJob.export_filename}`}
                    download
                    leftSection={<IconDownload size={16} />}
                    color="teal"
                  >
                    Download
                  </Button>
                </Group>
              </Card>
            )}

          </Stack>
        )}
      </Group>
    </Box>
  );
}
