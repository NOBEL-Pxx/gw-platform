/**
 * v4.48: AI Configuration Admin Page (Fix #3)
 *
 * Visual config editor for system prompts, classification thresholds,
 * and band configurations. Uses Ant Design forms with Aurora dark theme.
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Card,
  Tabs,
  Form,
  Input,
  InputNumber,
  Button,
  Select,
  Typography,
  Tag,
  message,
  Spin,
} from 'antd'
import SettingOutlined from '@ant-design/icons/SettingOutlined'
import SaveOutlined from '@ant-design/icons/SaveOutlined'
import ReloadOutlined from '@ant-design/icons/ReloadOutlined'
import ThunderboltOutlined from '@ant-design/icons/ThunderboltOutlined'
import ControlOutlined from '@ant-design/icons/ControlOutlined'
import BgColorsOutlined from '@ant-design/icons/BgColorsOutlined'
import axios from 'axios'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

// Simple API wrappers (service.ts will be updated separately)
const api = {
  getConfig: (ns: string) => axios.get(`/pipeline/admin/config/${ns}`),
  updateConfig: (ns: string, data: Record<string, unknown>) =>
    axios.put(`/pipeline/admin/config/${ns}`, data),
  resetConfig: (ns: string) => axios.post(`/pipeline/admin/config/${ns}/reset`),
}

interface SurveyCfg {
  priority: number
  wavelength: string
  color: string
  bands: string[]
}

export default function AdminConfigPage() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [aiConfig, setAiConfig] = useState<Record<string, unknown>>({})
  const [thresholds, setThresholds] = useState<Record<string, unknown>>({})
  const [bands, setBands] = useState<Record<string, SurveyCfg>>({})
  const [aiForm] = Form.useForm()
  const [threshForm] = Form.useForm()

  const loadConfig = useCallback(async () => {
    setLoading(true)
    try {
      const [ai, th, bd] = await Promise.all([
        api.getConfig('ai').catch(() => ({ data: { config: {} } })),
        api.getConfig('thresholds').catch(() => ({ data: { config: {} } })),
        api
          .getConfig('bands')
          .catch(() => ({ data: { config: { surveys: {} } } })),
      ])
      const aiData = ai.data?.config || {}
      const thData = th.data?.config || {}
      const bdData = bd.data?.config?.surveys || {}

      setAiConfig(aiData)
      setThresholds(thData)
      setBands(bdData)
      aiForm.setFieldsValue(aiData)
      threshForm.setFieldsValue(thData)
    } catch (_e) {
      message.warning('Configuration may not be accessible. JWT auth required.')
    } finally {
      setLoading(false)
    }
  }, [aiForm, threshForm])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  const handleSaveAI = async () => {
    setSaving(true)
    try {
      const values = aiForm.getFieldsValue()
      await api.updateConfig('ai', values)
      message.success('AI configuration saved')
    } catch {
      message.error('Failed to save AI config')
    } finally {
      setSaving(false)
    }
  }

  const handleSaveThresholds = async () => {
    setSaving(true)
    try {
      const values = threshForm.getFieldsValue()
      await api.updateConfig('thresholds', values)
      message.success('Thresholds saved')
    } catch {
      message.error('Failed to save thresholds')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async (ns: string) => {
    try {
      await api.resetConfig(ns)
      message.success(`${ns} reset to defaults`)
      loadConfig()
    } catch {
      message.error('Failed to reset')
    }
  }

  const cardStyle = {
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: 16,
  }
  const cardHeaderStyle = { borderColor: 'rgba(255,255,255,0.06)' }

  if (loading)
    return <Spin size='large' className='flex justify-center mt-20' />

  const tabItems = [
    {
      key: 'ai',
      label: (
        <span>
          <ThunderboltOutlined /> AI Configuration
        </span>
      ),
      children: (
        <div className='space-y-4'>
          <Card
            style={cardStyle}
            styles={{ header: cardHeaderStyle }}
            title={
              <span className='text-white/85 font-bold text-sm'>
                System Prompt
              </span>
            }
            extra={
              <Button
                size='small'
                icon={<ReloadOutlined />}
                onClick={() => handleReset('ai')}
              >
                Reset
              </Button>
            }
          >
            <Form form={aiForm} layout='vertical' initialValues={aiConfig}>
              <Form.Item
                name='system_prompt'
                label={
                  <Text className='text-white/60 text-xs'>SYSTEM PROMPT</Text>
                }
              >
                <TextArea
                  rows={12}
                  style={{
                    background: 'rgba(0,0,0,0.3)',
                    color: '#00F0FF',
                    borderColor: 'rgba(255,255,255,0.1)',
                    fontFamily: 'monospace',
                    fontSize: 12,
                  }}
                />
              </Form.Item>
              <div className='grid grid-cols-4 gap-4'>
                <Form.Item
                  name='temperature'
                  label={
                    <Text className='text-white/60 text-xs'>Temperature</Text>
                  }
                >
                  <InputNumber
                    min={0}
                    max={2}
                    step={0.05}
                    style={{ width: '100%', background: 'rgba(0,0,0,0.3)' }}
                  />
                </Form.Item>
                <Form.Item
                  name='max_tokens'
                  label={
                    <Text className='text-white/60 text-xs'>Max Tokens</Text>
                  }
                >
                  <InputNumber
                    min={100}
                    max={8000}
                    step={100}
                    style={{ width: '100%', background: 'rgba(0,0,0,0.3)' }}
                  />
                </Form.Item>
                <Form.Item
                  name='max_tool_rounds'
                  label={
                    <Text className='text-white/60 text-xs'>
                      Max Tool Rounds
                    </Text>
                  }
                >
                  <InputNumber
                    min={1}
                    max={50}
                    style={{ width: '100%', background: 'rgba(0,0,0,0.3)' }}
                  />
                </Form.Item>
                <Form.Item
                  name='model'
                  label={<Text className='text-white/60 text-xs'>Model</Text>}
                >
                  <Select
                    options={[
                      { value: 'deepseek-chat', label: 'DeepSeek Chat' },
                      {
                        value: 'deepseek-reasoner',
                        label: 'DeepSeek Reasoner',
                      },
                    ]}
                    style={{ background: 'rgba(0,0,0,0.3)' }}
                  />
                </Form.Item>
              </div>
              <Button
                type='primary'
                icon={<SaveOutlined />}
                loading={saving}
                onClick={handleSaveAI}
                style={{
                  background: '#00F0FF',
                  borderColor: '#00F0FF',
                  color: '#000',
                  fontWeight: 600,
                }}
              >
                Save AI Config
              </Button>
            </Form>
          </Card>
        </div>
      ),
    },
    {
      key: 'thresholds',
      label: (
        <span>
          <ControlOutlined /> Classification Thresholds
        </span>
      ),
      children: (
        <Card
          style={cardStyle}
          styles={{ header: cardHeaderStyle }}
          title={
            <span className='text-white/85 font-bold text-sm'>
              Anomaly Detection Thresholds
            </span>
          }
          extra={
            <Button
              size='small'
              icon={<ReloadOutlined />}
              onClick={() => handleReset('thresholds')}
            >
              Reset
            </Button>
          }
        >
          <Form form={threshForm} layout='vertical' initialValues={thresholds}>
            <div className='grid grid-cols-3 gap-4'>
              <Form.Item
                name='spike_sigma'
                label={
                  <Text className='text-white/60 text-xs'>Spike Sigma</Text>
                }
              >
                <InputNumber
                  min={1}
                  max={20}
                  step={0.5}
                  style={{ width: '100%', background: 'rgba(0,0,0,0.3)' }}
                />
              </Form.Item>
              <Form.Item
                name='dip_sigma'
                label={<Text className='text-white/60 text-xs'>Dip Sigma</Text>}
              >
                <InputNumber
                  min={1}
                  max={20}
                  step={0.5}
                  style={{ width: '100%', background: 'rgba(0,0,0,0.3)' }}
                />
              </Form.Item>
              <Form.Item
                name='pattern_break_sigma'
                label={
                  <Text className='text-white/60 text-xs'>
                    Pattern Break Sigma
                  </Text>
                }
              >
                <InputNumber
                  min={1}
                  max={20}
                  step={0.5}
                  style={{ width: '100%', background: 'rgba(0,0,0,0.3)' }}
                />
              </Form.Item>
              <Form.Item
                name='dl_anomaly_z_threshold'
                label={
                  <Text className='text-white/60 text-xs'>DL Z-Threshold</Text>
                }
              >
                <InputNumber
                  min={0.5}
                  max={10}
                  step={0.1}
                  style={{ width: '100%', background: 'rgba(0,0,0,0.3)' }}
                />
              </Form.Item>
              <Form.Item
                name='window_size'
                label={
                  <Text className='text-white/60 text-xs'>Window Size</Text>
                }
              >
                <InputNumber
                  min={16}
                  max={256}
                  step={16}
                  style={{ width: '100%', background: 'rgba(0,0,0,0.3)' }}
                />
              </Form.Item>
              <Form.Item
                name='fact_verifier_deviation_pct'
                label={
                  <Text className='text-white/60 text-xs'>
                    Verifier Deviation %
                  </Text>
                }
              >
                <InputNumber
                  min={0.05}
                  max={0.5}
                  step={0.01}
                  style={{ width: '100%', background: 'rgba(0,0,0,0.3)' }}
                />
              </Form.Item>
            </div>
            <Button
              type='primary'
              icon={<SaveOutlined />}
              loading={saving}
              onClick={handleSaveThresholds}
              style={{
                background: '#FF006E',
                borderColor: '#FF006E',
                fontWeight: 600,
              }}
            >
              Save Thresholds
            </Button>
          </Form>
        </Card>
      ),
    },
    {
      key: 'bands',
      label: (
        <span>
          <BgColorsOutlined /> Band Configuration
        </span>
      ),
      children: (
        <Card
          style={cardStyle}
          styles={{ header: cardHeaderStyle }}
          title={
            <span className='text-white/85 font-bold text-sm'>
              Survey Band Definitions
            </span>
          }
        >
          <div className='space-y-3'>
            {Object.entries(bands).map(([survey, cfg]) => (
              <div
                key={survey}
                className='flex items-center gap-4 p-3 rounded-lg'
                style={{
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,255,255,0.06)',
                }}
              >
                <Tag
                  color={cfg.color}
                  style={{ fontWeight: 700, minWidth: 80, textAlign: 'center' }}
                >
                  {survey}
                </Tag>
                <Tag>{cfg.wavelength}</Tag>
                <Text
                  className='text-white/60 text-xs'
                  style={{ fontFamily: 'monospace' }}
                >
                  {cfg.bands.join(', ')}
                </Text>
                <Text className='text-white/40 text-xs ml-auto'>
                  priority: {cfg.priority}
                </Text>
              </div>
            ))}
          </div>
          <Paragraph className='!mt-4 text-xs text-white/35'>
            Band configuration is managed in the pipeline defaults. Use the
            Config API (PUT /pipeline/admin/config/bands) to modify.
          </Paragraph>
        </Card>
      ),
    },
  ]

  return (
    <div className='h-full overflow-auto' style={{ background: 'transparent' }}>
      <div className='max-w-4xl mx-auto p-6 space-y-5'>
        <div className='flex items-center gap-3 mb-2'>
          <SettingOutlined className='text-aurora-cyan text-2xl' />
          <Title
            level={3}
            className='!mb-0 !text-white/90'
            style={{ fontWeight: 700 }}
          >
            AI Configuration
          </Title>
          <Tag color='cyan' className='font-semibold'>
            v4.48
          </Tag>
        </div>

        <Tabs
          items={tabItems}
          tabBarStyle={{ borderColor: 'rgba(255,255,255,0.08)' }}
          tabBarExtraContent={
            <Button
              icon={<ReloadOutlined />}
              onClick={loadConfig}
              size='small'
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(255,255,255,0.1)',
                color: '#fff',
              }}
            >
              Reload All
            </Button>
          }
        />

        <div className='text-center pt-2 pb-6'>
          <Text className='text-white/35 text-xs'>
            Configuration changes take effect immediately on next agent run. No
            redeploy required. · v4.48
          </Text>
        </div>
      </div>
    </div>
  )
}
