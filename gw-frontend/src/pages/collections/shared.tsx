import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Table, Empty, Spin } from 'antd'
import FolderOpenOutlined from '@ant-design/icons/FolderOpenOutlined'
import { getSharedCollection } from '@/service'
import type { CollectionDataItem } from '@/types/api'
import type { ColumnsType } from 'antd/es/table'

export default function SharedCollectionPage() {
  const { token } = useParams<{ token: string }>()
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [items, setItems] = useState<CollectionDataItem[]>([])

  useEffect(() => {
    let active = true
    if (!token) {
      setNotFound(true)
      setLoading(false)
      return
    }
    setLoading(true)
    getSharedCollection(token)
      .then((res) => {
        if (!active) return
        const d = res.data
        setName(d?.name || 'Untitled collection')
        setDescription(d?.description || '')
        setItems(d?.items || [])
      })
      .catch(() => {
        if (active) setNotFound(true)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [token])

  const columns: ColumnsType<CollectionDataItem> = [
    {
      title: 'Band',
      dataIndex: 'band',
      width: 120,
      render: (v: string) => <span className='text-white/85'>{v || '-'}</span>,
    },
    {
      title: 'RA',
      dataIndex: 'ra',
      width: 130,
      render: (v: number) => (
        <span className='text-white/60 font-mono'>{v ?? '-'}</span>
      ),
    },
    {
      title: 'Dec',
      dataIndex: 'dec',
      width: 130,
      render: (v: number) => (
        <span className='text-white/60 font-mono'>{v ?? '-'}</span>
      ),
    },
    {
      title: 'Telescope',
      dataIndex: 'telescope',
      width: 160,
      render: (v: string) => <span className='text-white/60'>{v || '-'}</span>,
    },
    {
      title: 'Data ID',
      dataIndex: 'grawaveId',
      render: (v: string) => (
        <span className='text-white/50 font-mono text-xs'>{v || '-'}</span>
      ),
    },
  ]

  if (loading) {
    return (
      <div className='flex items-center justify-center h-full'>
        <Spin size='large' />
      </div>
    )
  }

  if (notFound) {
    return (
      <div className='flex items-center justify-center h-full'>
        <Empty description='Shared collection not found or link is invalid'>
          <Link to='/' className='text-aurora-cyan text-sm font-semibold'>
            Return Home
          </Link>
        </Empty>
      </div>
    )
  }

  return (
    <div className='p-6 max-w-5xl mx-auto'>
      <h1 className='text-2xl font-bold text-white/90 mb-1 flex items-center gap-2'>
        <FolderOpenOutlined className='text-aurora-cyan' /> {name}
      </h1>
      {description && (
        <p className='text-white/50 text-sm mb-4'>{description}</p>
      )}
      <p className='text-white/45 text-sm mb-4'>
        Shared collection · {items.length} item{items.length === 1 ? '' : 's'}
      </p>
      <Table
        columns={columns}
        dataSource={items}
        rowKey='id'
        pagination={false}
        locale={{
          emptyText: <Empty description='This collection has no items yet.' />,
        }}
        scroll={{ x: 700 }}
      />
    </div>
  )
}
