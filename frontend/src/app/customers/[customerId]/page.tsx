'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import {
  Badge,
  Box,
  Button,
  Card,
  Group,
  Progress,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Timeline,
  Title,
} from '@mantine/core';
import { IconArrowLeft, IconCircleCheck, IconClock, IconPlayerPlay } from '@tabler/icons-react';

import { api, type CustomerDeployment, type CustomerRecord, type ServiceTimelineEvent } from '@/lib/api';

const glassStyle = {
  background: 'rgba(255,255,255,0.05)',
  backdropFilter: 'blur(8px)',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: '16px',
};

export default function CustomerDetailPage() {
  const params = useParams<{ customerId: string }>();
  const customerId = params.customerId;

  const [customer, setCustomer] = useState<CustomerRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedServiceId, setSelectedServiceId] = useState<string | null>(null);
  const [timelineEvents, setTimelineEvents] = useState<ServiceTimelineEvent[]>([]);
  const [deployments, setDeployments] = useState<CustomerDeployment[]>([]);
  const [deploymentQuery, setDeploymentQuery] = useState('');
  const [qrFilter, setQrFilter] = useState<string>('all');

  const loadCustomer = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.customer(customerId);
      setCustomer(data);
      const deploymentResponse = await api.customerDeployments(customerId);
      setDeployments(deploymentResponse.deployments);
      if (data.services.length > 0) {
        setSelectedServiceId((prev) => prev ?? data.services[0].id);
      }
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  const loadTimeline = useCallback(async (serviceId: string) => {
    const timeline = await api.customerServiceTimeline(customerId, serviceId);
    setTimelineEvents(timeline.events);
  }, [customerId]);

  useEffect(() => {
    if (!customerId) {
      return;
    }
    void loadCustomer();
  }, [customerId, loadCustomer]);

  useEffect(() => {
    if (!selectedServiceId) {
      setTimelineEvents([]);
      return;
    }
    void loadTimeline(selectedServiceId);
  }, [selectedServiceId, loadTimeline]);

  const tokenUsagePercent = useMemo(() => {
    if (!customer || customer.monthly_token_budget <= 0) {
      return 0;
    }
    return (customer.tokens_used_this_month / customer.monthly_token_budget) * 100;
  }, [customer]);

  const filteredDeployments = useMemo(() => {
    const query = deploymentQuery.trim().toLowerCase();
    return deployments.filter((deployment) => {
      const matchesQuery =
        query.length === 0 ||
        deployment.project_id.toLowerCase().includes(query) ||
        (deployment.project_slug || '').toLowerCase().includes(query) ||
        deployment.deployed_url.toLowerCase().includes(query);

      const hasQr = Boolean(deployment.qr_path);
      const matchesQr =
        qrFilter === 'all' ||
        (qrFilter === 'with' && hasQr) ||
        (qrFilter === 'without' && !hasQr);

      return matchesQuery && matchesQr;
    });
  }, [deployments, deploymentQuery, qrFilter]);

  if (!customer) {
    return (
      <Stack p="xl">
        <Group>
          <Button component={Link} href="/customers" leftSection={<IconArrowLeft size={16} />} variant="default">
            Back
          </Button>
        </Group>
        <Text c="dimmed">{loading ? 'Loading customer...' : 'Customer not found.'}</Text>
      </Stack>
    );
  }

  return (
    <Stack p="xl" gap="lg">
      <Group justify="space-between">
        <Group>
          <Button component={Link} href="/customers" leftSection={<IconArrowLeft size={16} />} variant="default">
            Back
          </Button>
          <Box>
            <Title order={2}>{customer.business_name}</Title>
            <Text c="dimmed">{customer.email}</Text>
          </Box>
        </Group>
        <Badge variant="light">{customer.tier}</Badge>
      </Group>

      <Group grow>
        <Card style={glassStyle}>
          <Text c="dimmed" size="sm">Website</Text>
          <Text fw={600}>{customer.website_url || 'Not assigned'}</Text>
        </Card>
        <Card style={glassStyle}>
          <Text c="dimmed" size="sm">Services</Text>
          <Text fw={600}>{customer.services.length}</Text>
        </Card>
        <Card style={glassStyle}>
          <Text c="dimmed" size="sm">Token Usage</Text>
          <Progress value={tokenUsagePercent} size="sm" mt={6} />
          <Text size="xs" c="dimmed" mt={4}>
            {customer.tokens_used_this_month.toLocaleString()} / {customer.monthly_token_budget.toLocaleString()}
          </Text>
        </Card>
      </Group>

      <Tabs defaultValue="services">
        <Tabs.List>
          <Tabs.Tab value="overview">Overview</Tabs.Tab>
          <Tabs.Tab value="services">Services</Tabs.Tab>
          <Tabs.Tab value="agents">Agents</Tabs.Tab>
          <Tabs.Tab value="assets">Assets</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="overview" pt="md">
          <Card style={glassStyle}>
            <Stack>
              <Text>Customer ID: {customer.id}</Text>
              <Text>Business Name: {customer.business_name}</Text>
              <Text>Tier: {customer.tier}</Text>
              <Text>Social Accounts: {Object.keys(customer.social_media_accounts).length}</Text>
            </Stack>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="services" pt="md">
          <Stack>
            <Card style={glassStyle}>
              <Table striped highlightOnHover withTableBorder>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Service</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th>Progress</Table.Th>
                    <Table.Th>Assigned Agents</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {customer.services.map((service) => (
                    <Table.Tr key={service.id}>
                      <Table.Td>{service.type}</Table.Td>
                      <Table.Td><Badge>{service.status}</Badge></Table.Td>
                      <Table.Td style={{ minWidth: 160 }}>
                        <Progress value={service.progress_percent} size="sm" />
                      </Table.Td>
                      <Table.Td>{service.assigned_agents.join(', ') || 'None'}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Card>

            <Card style={glassStyle}>
              <Stack>
                <Title order={5}>Service Timeline</Title>
                <Select
                  label="Select service"
                  data={customer.services.map((service) => ({ value: service.id, label: `${service.type} (${service.id})` }))}
                  value={selectedServiceId}
                  onChange={setSelectedServiceId}
                />

                {timelineEvents.length === 0 ? (
                  <Text size="sm" c="dimmed">No timeline events yet.</Text>
                ) : (
                  <Timeline active={timelineEvents.length - 1} bulletSize={20} lineWidth={2}>
                    {timelineEvents.map((event) => (
                      <Timeline.Item
                        key={event.id}
                        title={event.event_type}
                        bullet={
                          event.event_type.includes('created') ? <IconClock size={12} /> :
                          event.event_type.includes('assigned') ? <IconPlayerPlay size={12} /> :
                          <IconCircleCheck size={12} />
                        }
                      >
                        <Text size="sm">{event.detail}</Text>
                        <Text size="xs" c="dimmed">{new Date(event.created_at).toLocaleString()}</Text>
                      </Timeline.Item>
                    ))}
                  </Timeline>
                )}
              </Stack>
            </Card>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="agents" pt="md">
          <Card style={glassStyle}>
            <Stack>
              <Text c="dimmed" size="sm">Agents currently assigned to active services</Text>
              <Group>
                {Array.from(new Set(customer.services.flatMap((service) => service.assigned_agents))).map((agent) => (
                  <Badge key={agent} color="blue" variant="light">{agent}</Badge>
                ))}
              </Group>
            </Stack>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="assets" pt="md">
          <Card style={glassStyle}>
            <Stack>
              <Text>Website: {customer.website_url || 'Not assigned'}</Text>
              <Group>
                <Button component={Link} href={`/webgen?customerId=${customer.id}`} size="xs" variant="light">
                  Build / Deploy Website
                </Button>
                <Button component={Link} href={`/marketing?customerId=${customer.id}`} size="xs" variant="default">
                  Demo Marketing Assistant
                </Button>
              </Group>
              {Object.entries(customer.social_media_accounts).length === 0 ? (
                <Text c="dimmed" size="sm">No social media accounts linked yet.</Text>
              ) : (
                Object.entries(customer.social_media_accounts).map(([platform, url]) => (
                  <Text key={platform}>{platform}: {url}</Text>
                ))
              )}

              <Title order={5} mt="md">Deployment History</Title>
              {deployments.length === 0 ? (
                <Text c="dimmed" size="sm">No deployments recorded yet.</Text>
              ) : (
                <Stack>
                  <Group grow>
                    <TextInput
                      label="Search deployments"
                      placeholder="Project, slug, or URL"
                      value={deploymentQuery}
                      onChange={(event) => setDeploymentQuery(event.currentTarget.value)}
                    />
                    <Select
                      label="QR Filter"
                      value={qrFilter}
                      onChange={(value) => setQrFilter(value || 'all')}
                      data={[
                        { value: 'all', label: 'All' },
                        { value: 'with', label: 'With QR' },
                        { value: 'without', label: 'Without QR' },
                      ]}
                    />
                  </Group>

                  <Table withTableBorder striped>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Project</Table.Th>
                      <Table.Th>URL</Table.Th>
                      <Table.Th>QR</Table.Th>
                      <Table.Th>Deployed</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {filteredDeployments.map((deployment) => (
                      <Table.Tr key={deployment.id}>
                        <Table.Td>{deployment.project_slug || deployment.project_id}</Table.Td>
                        <Table.Td>
                          <a href={deployment.deployed_url} target="_blank" rel="noreferrer">{deployment.deployed_url}</a>
                        </Table.Td>
                        <Table.Td>
                          {deployment.qr_path ? (
                            <Button
                              component="a"
                              href={api.webgenQrFileUrl(deployment.qr_path)}
                              target="_blank"
                              rel="noreferrer"
                              size="xs"
                              variant="light"
                            >
                              Open QR
                            </Button>
                          ) : (
                            'n/a'
                          )}
                        </Table.Td>
                        <Table.Td>{new Date(deployment.deployed_at).toLocaleString()}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                  </Table>
                  {filteredDeployments.length === 0 && (
                    <Text c="dimmed" size="sm">No deployments match current filters.</Text>
                  )}
                </Stack>
              )}
            </Stack>
          </Card>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
