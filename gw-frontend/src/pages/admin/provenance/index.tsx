/**
 * v4.48: Data Provenance & DOI Management Page (Fix #4)
 *
 * Register DOIs, browse citations, view provenance chains.
 * Uses Ant Design Table + Timeline in Aurora dark theme.
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Tag,
  Typography,
  message,
  Timeline,
  Space,
} from 'antd'
import LinkOutlined from '@ant-design/icons/LinkOutlined'
import PlusOutlined from '@ant-design/icons/PlusOutlined'
import ExportOutlined from '@ant-design/icons/ExportOutlined'
import NodeIndexOutlined from '@ant-design/icons/NodeIndexOutlined'
import HistoryOutlined from '@ant-design/icons/HistoryOutlined'
import FileTextOutlined from '@ant-design/icons/FileTextOutlined'
import axios from 'axios'

const { Title, Text } = Typography
const { TextArea } = Input

interface DOIRecord {
  doi: string
  title: string
  creators: string[]
  publisher: string
  publication_year: number
  resource_type: string
  description: string
  survey: string
  bands: string[]
  created_at: string
  file_count: number
  observation_ids: string[]
}

export default function AdminProvenancePage() {
  const [loading, setLoading] = useState(true)
  const [dois, setDois] = useState<DOIRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [modalOpen, setModalOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [chainOpen, setChainOpen] = useState(false)
  const [chain, setChain] = useState<Array<{ type: string; data: unknown }>>([])
  const [form] = Form.useForm()

  const fetchDOIs = useCallback(async (p: number = 1) => {
    setLoading(true)
    try {
      const resp = await axios.get('/pipeline/provenance/dois', {
        params: { page: p, page_size: 20 },
      })
      setDois(resp.data?.dois || [])
      setTotal(resp.data?.total || 0)
    } catch {
      message.warning('Provenance API may require authentication.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDOIs(page)
  }, [fetchDOIs, page])

  const handleRegister = async () => {
    setSubmitting(true)
    try {
      const values = form.getFieldsValue()
      await axios.post('/pipeline/provenance/doi', {
        ...values,
        creators: values.creators
          ? values.creators.split(',').map((s: string) => s.trim())
          : [],
        bands: values.bands
          ? values.bands.split(',').map((s: string) => s.trim())
          : [],
      })
      message.success('DOI registered')
      setModalOpen(false)
      form.resetFields()
      fetchDOIs(page)
    } catch {
      message.error('Failed to register DOI')
    } finally {
      setSubmitting(false)
    }
  }

  const handleViewChain = async (doi: string) => {
    try {
      const obsIds = dois.find((d) => d.doi === doi)?.observation_ids || []
      if (obsIds.length > 0) {
        const resp = await axios.get(`/pipeline/provenance/chain/${obsIds[0]}`)
        setChain(resp.data?.chain || [])
      } else {
        setChain([])
      }
      setChainOpen(true)
    } catch {
      message.error('Failed to load provenance chain')
    }
  }

  const cardStyle = {
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: 16,
  }
  const cardHeaderStyle = { borderColor: 'rgba(255,255,255,0.06)' }

  const columns = [
    {
      title: 'DOI',
      dataIndex: 'doi',
      key: 'doi',
      render: (doi: string) => (
        <a
          href={`https://doi.org/${doi}`}
          target='_blank'
          rel='noopener noreferrer'
          className='text-aurora-cyan hover:text-aurora-cyan/80'
          style={{ fontFamily: 'monospace', fontSize: 12 }}
        >
          <LinkOutlined className='mr-1' />
          {doi}
        </a>
      ),
    },
    {
      title: 'Title',
      dataIndex: 'title',
      key: 'title',
      render: (t: string) => <Text className='text-white/85 text-sm'>{t}</Text>,
    },
    {
      title: 'Survey',
      dataIndex: 'survey',
      key: 'survey',
      render: (s: string) => (s ? <Tag color='cyan'>{s}</Tag> : <Tag>—</Tag>),
    },
    {
      title: 'Type',
      dataIndex: 'resource_type',
      key: 'type',
      render: (t: string) => <Tag>{t}</Tag>,
    },
    {
      title: 'Year',
      dataIndex: 'publication_year',
      key: 'year',
      width: 70,
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 160,
      render: (_: unknown, record: DOIRecord) => (
        <Space>
          <Button
            size='small'
            icon={<NodeIndexOutlined />}
            onClick={() => handleViewChain(record.doi)}
          >
            Chain
          </Button>
          <Button
            size='small'
            icon={<ExportOutlined />}
            onClick={() => {
              const bibtex = `@dataset{${record.doi.replace(/[^a-zA-Z0-9]/g, '_')},\n  title = {${record.title}},\n  author = {${(record.creators || []).join(' and ')}},\n  year = {${record.publication_year}},\n  publisher = {${record.publisher}},\n  doi = {${record.doi}}\n}`
              navigator.clipboard.writeText(bibtex)
              message.success('BibTeX copied to clipboard')
            }}
          >
            BibTeX
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div className='h-full overflow-auto' style={{ background: 'transparent' }}>
      <div className='max-w-5xl mx-auto p-6 space-y-5'>
        <div className='flex items-center justify-between'>
          <div className='flex items-center gap-3'>
            <FileTextOutlined className='text-aurora-cyan text-2xl' />
            <Title
              level={3}
              className='!mb-0 !text-white/90'
              style={{ fontWeight: 700 }}
            >
              Data Provenance
            </Title>
            <Tag color='cyan' className='font-semibold'>
              v4.48
            </Tag>
          </div>
          <Button
            type='primary'
            icon={<PlusOutlined />}
            onClick={() => setModalOpen(true)}
            style={{
              background: '#00F0FF',
              borderColor: '#00F0FF',
              color: '#000',
              fontWeight: 600,
            }}
          >
            Register DOI
          </Button>
        </div>

        <Card
          style={cardStyle}
          styles={{ header: cardHeaderStyle }}
          title={
            <span className='text-white/85 font-bold text-sm'>
              DOI Registry ({total} records)
            </span>
          }
        >
          <Table
            dataSource={dois}
            columns={columns}
            rowKey='doi'
            loading={loading}
            size='small'
            pagination={{
              current: page,
              total,
              pageSize: 20,
              onChange: (p) => setPage(p),
            }}
            style={{ background: 'transparent' }}
            rowClassName={() => 'text-white/80'}
          />
        </Card>

        {/* Register DOI Modal */}
        <Modal
          title={<span className='text-white/90'>Register New DOI</span>}
          open={modalOpen}
          onCancel={() => setModalOpen(false)}
          onOk={handleRegister}
          confirmLoading={submitting}
          styles={{
            content: {
              background: '#0A0F1E',
              border: '1px solid rgba(255,255,255,0.1)',
            },
            header: { background: 'transparent' },
          }}
        >
          <Form form={form} layout='vertical'>
            <Form.Item name='title' label='Title' rules={[{ required: true }]}>
              <Input placeholder='Dataset title' />
            </Form.Item>
            <Form.Item name='creators' label='Creators (comma-separated)'>
              <Input placeholder='Smith, J., Wang, L.' />
            </Form.Item>
            <Form.Item name='description' label='Description'>
              <TextArea rows={3} />
            </Form.Item>
            <div className='grid grid-cols-2 gap-3'>
              <Form.Item name='resource_type' label='Type'>
                <Select
                  options={[
                    { value: 'Dataset', label: 'Dataset' },
                    { value: 'Software', label: 'Software' },
                    { value: 'Image', label: 'Image' },
                  ]}
                />
              </Form.Item>
              <Form.Item name='survey' label='Survey'>
                <Input placeholder='AliCPT, DSS2, ...' />
              </Form.Item>
            </div>
            <Form.Item name='bands' label='Bands (comma-separated)'>
              <Input placeholder='150 GHz, Blue, Red' />
            </Form.Item>
          </Form>
        </Modal>

        {/* Provenance Chain Modal */}
        <Modal
          title={
            <span className='text-white/90'>
              <HistoryOutlined className='mr-2' />
              Provenance Chain
            </span>
          }
          open={chainOpen}
          onCancel={() => setChainOpen(false)}
          footer={null}
          width={600}
          styles={{
            content: {
              background: '#0A0F1E',
              border: '1px solid rgba(255,255,255,0.1)',
            },
          }}
        >
          {chain.length === 0 ? (
            <Text className='text-white/50'>
              No provenance chain data available.
            </Text>
          ) : (
            <Timeline
              items={chain.map((item, i) => ({
                color: item.type === 'doi' ? 'cyan' : 'green',
                children: (
                  <div>
                    <Tag color={item.type === 'doi' ? 'cyan' : 'green'}>
                      {item.type}
                    </Tag>
                    <Text className='text-white/70 text-xs ml-2'>
                      {item.type === 'doi'
                        ? ((item.data as Record<string, unknown>)
                            ?.title as string)
                        : `Provenance record #${i + 1}`}
                    </Text>
                  </div>
                ),
              }))}
            />
          )}
        </Modal>

        <div className='text-center pt-2 pb-6'>
          <Text className='text-white/35 text-xs'>
            DOI registration and provenance tracking · v4.48 · Scientific data
            platform
          </Text>
        </div>
      </div>
    </div>
  )
}
