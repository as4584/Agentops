'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import {
  ActionIcon,
  Box,
  Button,
  Card,
  Group,
  Loader,
  Select,
  Stack,
  Stepper,
  Text,
  TextInput,
  Textarea,
  Title,
} from '@mantine/core';
import { IconArrowLeft } from '@tabler/icons-react';

import { api, type CustomerRecord, type WebgenProjectItem } from '@/lib/api';

const glassStyle = {
  background: 'rgba(255,255,255,0.05)',
  backdropFilter: 'blur(8px)',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: '16px',
};

function WebgenPageInner() {
  const searchParams = useSearchParams();
  const preselectedCustomerId = searchParams.get('customerId');

  const [active, setActive] = useState(0);
  const [businessName, setBusinessName] = useState('');
  const [businessType, setBusinessType] = useState('custom');
  const [tagline, setTagline] = useState('');
  const [description, setDescription] = useState('');
  const [tone, setTone] = useState('professional');
  const [servicesRaw, setServicesRaw] = useState('');

  const [projectId, setProjectId] = useState<string>('');
  const [projectSlug, setProjectSlug] = useState<string>('');
  const [generatedHtml, setGeneratedHtml] = useState('');
  const [deployUrl, setDeployUrl] = useState('');
  const [qrPath, setQrPath] = useState('');
  const [loading, setLoading] = useState(false);

  const [projects, setProjects] = useState<WebgenProjectItem[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [customers, setCustomers] = useState<CustomerRecord[]>([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(preselectedCustomerId);

  async function refreshProjects() {
    const response = await api.webgenProjects();
    setProjects(response.projects);
  }

  useEffect(() => {
    void refreshProjects();
    void api.customers().then((items) => {
      setCustomers(items);
      if (items.length > 0) {
        setSelectedCustomerId((prev) => prev ?? items[0].id);
      }
    });
  }, []);

  const canGenerate = useMemo(() => businessName.trim().length > 1, [businessName]);

  async function handleGenerate() {
    if (!canGenerate) {
      return;
    }
    setLoading(true);
    try {
      const response = await api.webgenGenerate({
        business_name: businessName,
        business_type: businessType,
        tagline,
        description,
        tone,
        services: servicesRaw.split(',').map((service) => service.trim()).filter(Boolean),
        customer_id: selectedCustomerId || undefined,
      });

      setProjectId(response.project_id);
      setProjectSlug(response.project_slug);
      setGeneratedHtml(response.html);
      setActive(1);
      await refreshProjects();
    } finally {
      setLoading(false);
    }
  }

  async function handleLoadProject() {
    if (!selectedProject) {
      return;
    }
    setLoading(true);
    try {
      const project = await api.webgenProject(selectedProject);
      setProjectId(project.project_id);
      setProjectSlug(project.project_slug);
      setGeneratedHtml(project.html);
      setDeployUrl(project.status === 'deployed' ? project.deployed_url || '' : '');
      setActive(1);
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveEdits() {
    if (!projectId || generatedHtml.trim().length < 10) {
      return;
    }
    setLoading(true);
    try {
      await api.webgenSavePage(projectId, generatedHtml);
      setActive(2);
    } finally {
      setLoading(false);
    }
  }

  async function handleDeploy() {
    if (!projectId) {
      return;
    }
    setLoading(true);
    try {
      const deployed = await api.webgenDeploy(projectId, selectedCustomerId || undefined);
      setDeployUrl(deployed.deployed_url);
      setQrPath(deployed.qr_path || '');
      if (!deployed.qr_path) {
        const qr = await api.webgenQR(projectId, deployed.deployed_url);
        setQrPath(qr.qr_path);
      }
      setActive(3);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Stack p="xl" gap="lg">
      <Group gap="sm">
        <ActionIcon component={Link} href="/" variant="subtle" size="lg" aria-label="Back to dashboard">
          <IconArrowLeft size={20} />
        </ActionIcon>
        <Title order={2}>Website Maker</Title>
      </Group>
      <Text c="dimmed">Generate 90%, edit final details, deploy to Vercel, and generate QR code.</Text>

      <Card style={glassStyle}>
        <Group align="flex-end" grow>
          <Select
            label="Linked Customer"
            placeholder="Optional customer link"
            value={selectedCustomerId}
            onChange={setSelectedCustomerId}
            data={customers.map((customer) => ({
              value: customer.id,
              label: `${customer.business_name} (${customer.tier})`,
            }))}
            clearable
          />
          <Select
            label="Existing Project"
            placeholder="Select a generated project"
            value={selectedProject}
            onChange={setSelectedProject}
            data={projects.map((project) => ({
              value: project.id,
              label: `${project.business_name} (${project.status})`,
            }))}
          />
          <Button onClick={handleLoadProject} disabled={!selectedProject}>Load</Button>
        </Group>
      </Card>

      <Stepper active={active} onStepClick={setActive}>
        <Stepper.Step label="Generate" description="AI draft">
          <Card style={glassStyle}>
            <Stack>
              <TextInput label="Business Name" value={businessName} onChange={(e) => setBusinessName(e.currentTarget.value)} required />
              <Select
                label="Business Type"
                value={businessType}
                onChange={(value) => setBusinessType(value || 'custom')}
                data={[
                  { value: 'automotive', label: 'Automotive' },
                  { value: 'agency', label: 'Agency' },
                  { value: 'restaurant', label: 'Restaurant' },
                  { value: 'custom', label: 'Custom' },
                ]}
              />
              <TextInput label="Tagline" value={tagline} onChange={(e) => setTagline(e.currentTarget.value)} />
              <Textarea label="Description" value={description} minRows={4} onChange={(e) => setDescription(e.currentTarget.value)} />
              <TextInput label="Services (comma separated)" value={servicesRaw} onChange={(e) => setServicesRaw(e.currentTarget.value)} />
              <Select
                label="Tone"
                value={tone}
                onChange={(value) => setTone(value || 'professional')}
                data={[
                  { value: 'professional', label: 'Professional' },
                  { value: 'friendly', label: 'Friendly' },
                  { value: 'bold', label: 'Bold' },
                ]}
              />
              <Group justify="flex-end">
                <Button onClick={handleGenerate} disabled={!canGenerate || loading}>Generate Website</Button>
              </Group>
            </Stack>
          </Card>
        </Stepper.Step>

        <Stepper.Step label="Edit" description="Finalize content">
          <Card style={glassStyle}>
            <Stack>
              <Text size="sm" c="dimmed">Project: {projectId || 'Not generated'} · Slug: {projectSlug || '-'}</Text>
              <Textarea
                label="HTML Editor"
                minRows={18}
                value={generatedHtml}
                onChange={(e) => setGeneratedHtml(e.currentTarget.value)}
                styles={{ input: { fontFamily: 'monospace' } }}
              />
              <Group justify="space-between">
                <Button variant="default" onClick={() => setActive(0)}>Back</Button>
                <Button onClick={handleSaveEdits} disabled={!projectId || loading}>Save Edits</Button>
              </Group>
            </Stack>
          </Card>
        </Stepper.Step>

        <Stepper.Step label="Deploy" description="Publish + QR">
          <Card style={glassStyle}>
            <Stack>
              <Text size="sm" c="dimmed">
                Deployment runs `vercel --yes --prod` in project output directory.
              </Text>
              <Group justify="space-between">
                <Button variant="default" onClick={() => setActive(1)}>Back</Button>
                <Button onClick={handleDeploy} disabled={!projectId || loading}>Deploy to Vercel</Button>
              </Group>
            </Stack>
          </Card>
        </Stepper.Step>

        <Stepper.Completed>
          <Card style={glassStyle}>
            <Stack>
              <Title order={4}>Deployment Completed</Title>
              <Text>Project ID: {projectId}</Text>
              <Text>Vercel URL: {deployUrl || 'Not available'}</Text>
              <Text>QR Path: {qrPath || 'Not generated'}</Text>
              {deployUrl && (
                <Button component="a" href={deployUrl} target="_blank" rel="noreferrer">
                  Open Live Site
                </Button>
              )}
            </Stack>
          </Card>
        </Stepper.Completed>
      </Stepper>

      {loading && (
        <Group>
          <Loader size="sm" />
          <Text size="sm" c="dimmed">Processing...</Text>
        </Group>
      )}

      {generatedHtml && (
        <Card style={glassStyle}>
          <Stack>
            <Text fw={600}>Preview</Text>
            <Box style={{ borderRadius: 8, overflow: 'hidden', border: '1px solid rgba(255,255,255,0.12)' }}>
              <iframe title="Generated site preview" srcDoc={generatedHtml} style={{ width: '100%', height: 420, border: 'none' }} />
            </Box>
          </Stack>
        </Card>
      )}
    </Stack>
  );
}

export default function WebgenPage() {
  return (
    <Suspense>
      <WebgenPageInner />
    </Suspense>
  );
}
