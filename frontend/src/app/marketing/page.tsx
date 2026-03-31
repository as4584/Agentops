'use client';

import { FormEvent, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  ActionIcon,
  Accordion,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  Textarea,
  Title,
} from '@mantine/core';
import { IconArrowLeft } from '@tabler/icons-react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

type FaqItem = { question: string; answer: string };

type AskResponse = {
  answer: string;
  model_id: string;
  provider: string;
  estimated_cost_usd: number;
};

type CustomerOption = {
  id: string;
  business_name: string;
  tier: string;
};

const glassStyle = {
  background: 'rgba(255,255,255,0.05)',
  backdropFilter: 'blur(8px)',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: '16px',
};

export default function MarketingPage() {
  const [faqs, setFaqs] = useState<FaqItem[]>([]);
  const [question, setQuestion] = useState('How does this help me get more customers?');
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [loadingFaq, setLoadingFaq] = useState(false);
  const [asking, setAsking] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [deployInfo, setDeployInfo] = useState<{ deployed_url: string; qr_path: string } | null>(null);
  const [customers, setCustomers] = useState<CustomerOption[]>([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null);

  async function loadFaq() {
    setLoadingFaq(true);
    try {
      const response = await fetch(`${API_BASE}/api/marketing/faq`);
      if (!response.ok) {
        return;
      }
      const data = await response.json();
      setFaqs(data.faqs || []);
    } finally {
      setLoadingFaq(false);
    }
  }

  async function loadCustomers() {
    const response = await fetch(`${API_BASE}/api/customers/`);
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    setCustomers(data || []);
    if (!selectedCustomerId && Array.isArray(data) && data.length > 0) {
      setSelectedCustomerId(data[0].id);
    }
  }

  useEffect(() => {
    void loadFaq();
    void loadCustomers();
  }, []);

  async function askQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim()) {
      return;
    }
    setAsking(true);
    try {
      const response = await fetch(`${API_BASE}/api/marketing/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, customer_id: selectedCustomerId }),
      });
      if (!response.ok) {
        setAnswer({
          answer: 'Request failed. Please verify backend availability and try again.',
          model_id: 'n/a',
          provider: 'n/a',
          estimated_cost_usd: 0,
        });
        return;
      }
      const data = await response.json();
      setAnswer(data);
    } finally {
      setAsking(false);
    }
  }

  async function deployMarketing() {
    setDeploying(true);
    try {
      const response = await fetch(`${API_BASE}/api/marketing/deploy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: 'frontend' }),
      });
      const data = await response.json();
      if (!response.ok) {
        setAnswer({
          answer: `Deploy failed: ${JSON.stringify(data.detail || data)}`,
          model_id: 'deploy',
          provider: 'system',
          estimated_cost_usd: 0,
        });
        return;
      }
      setDeployInfo({ deployed_url: data.deployed_url, qr_path: data.qr_path });
    } finally {
      setDeploying(false);
    }
  }

  return (
    <Stack p="xl" gap="lg">
      <Group gap="sm">
        <ActionIcon component={Link} href="/" variant="subtle" size="lg" aria-label="Back to dashboard">
          <IconArrowLeft size={20} />
        </ActionIcon>
        <Title order={2}>Marketing Site Console</Title>
      </Group>
      <Text c="dimmed">Business-owner-ready page with FAQ wall + AI assistant. Keep messaging direct and practical.</Text>

      <Card style={glassStyle}>
        <Stack>
          <Group justify="space-between">
            <Title order={4}>Deploy</Title>
            <Button onClick={deployMarketing} loading={deploying}>Deploy Marketing Site + QR</Button>
          </Group>
          {deployInfo && (
            <Stack gap={4}>
              <Text>Live URL: {deployInfo.deployed_url}</Text>
              <Text>QR File: {deployInfo.qr_path}</Text>
            </Stack>
          )}
        </Stack>
      </Card>

      <Card style={glassStyle}>
        <Stack>
          <Title order={4}>AI Assistant</Title>
          <Select
            label="Customer Context (optional)"
            value={selectedCustomerId}
            onChange={setSelectedCustomerId}
            data={customers.map((customer) => ({
              value: customer.id,
              label: `${customer.business_name} (${customer.tier})`,
            }))}
            placeholder="Choose a customer profile"
            clearable
          />
          <form onSubmit={askQuestion}>
            <Stack>
              <Textarea
                label="Ask any question"
                minRows={3}
                value={question}
                onChange={(e) => setQuestion(e.currentTarget.value)}
              />
              <Group justify="flex-end">
                <Button type="submit" loading={asking}>Ask Assistant</Button>
              </Group>
            </Stack>
          </form>
          {answer && (
            <Card withBorder>
              <Stack gap={6}>
                <Text>{answer.answer}</Text>
                <Group gap={8}>
                  <Badge variant="light">{answer.model_id}</Badge>
                  <Badge variant="light">{answer.provider}</Badge>
                  <Badge variant="light">${answer.estimated_cost_usd.toFixed(6)}</Badge>
                </Group>
              </Stack>
            </Card>
          )}
        </Stack>
      </Card>

      <Card style={glassStyle}>
        <Stack>
          <Title order={4}>FAQ Wall</Title>
          {loadingFaq ? (
            <Group><Loader size="sm" /><Text size="sm" c="dimmed">Loading FAQs...</Text></Group>
          ) : (
            <Accordion variant="separated">
              {faqs.map((faq, index) => (
                <Accordion.Item key={`${faq.question}-${index}`} value={`faq-${index}`}>
                  <Accordion.Control>{faq.question}</Accordion.Control>
                  <Accordion.Panel>{faq.answer}</Accordion.Panel>
                </Accordion.Item>
              ))}
            </Accordion>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}
