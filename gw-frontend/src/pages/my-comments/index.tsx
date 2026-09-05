import { useCallback, useEffect, useState } from 'react'
import { Table, Empty, Tag } from 'antd'
import CommentOutlined from '@ant-design/icons/CommentOutlined'
import { getCommentsByUserId } from '@/service'
import { useAuth } from '@/contexts/AuthContext'
import { CommentItem } from '@/types/api'
import type { ColumnsType } from 'antd/es/table'

const CATEGORY_COLOR: Record<string, string> = {
  alert: 'red',
  data_error: 'orange',
  false_alarm: 'blue',
  other: 'default',
}

export default function MyCommentsPage() {
  const { user } = useAuth()
  const [loading, setLoading] = useState(true)
  const [comments, setComments] = useState<CommentItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)

  const fetchComments = useCallback(
    async (p: number) => {
      if (!user) {
        setLoading(false)
        return
      }
      setLoading(true)
      try {
        const res = await getCommentsByUserId(user.userId, {
          page: p,
          size: 20,
        })
        setComments(res.data?.list || [])
        setTotal(res.data?.total_info?.total_count || 0)
      } catch {
        /* handled by interceptor */
      } finally {
        setLoading(false)
      }
    },
    [user],
  )

  useEffect(() => {
    fetchComments(page)
  }, [page, fetchComments])

  const columns: ColumnsType<CommentItem> = [
    {
      title: 'Content',
      dataIndex: 'content',
      render: (v: string) => <span className='text-white/85'>{v}</span>,
    },
    {
      title: 'Category',
      dataIndex: 'category',
      width: 130,
      render: (v: string) => (
        <Tag color={CATEGORY_COLOR[v] || 'default'}>{v || '-'}</Tag>
      ),
    },
    {
      title: 'Data ID',
      dataIndex: 'grawaveId',
      width: 180,
      render: (v: string) => (
        <span className='text-white/50 font-mono text-xs'>{v || '-'}</span>
      ),
    },
    {
      title: 'Time',
      dataIndex: 'createdAt',
      width: 200,
      render: (v: string) => v || '-',
    },
  ]

  if (!user) {
    return (
      <div className='flex items-center justify-center h-full'>
        <Empty description='Login to view your comments' />
      </div>
    )
  }

  return (
    <div className='p-6 max-w-5xl mx-auto'>
      <h1 className='text-2xl font-bold text-white/90 mb-2 flex items-center gap-2'>
        <CommentOutlined className='text-aurora-cyan' /> My Comments
      </h1>
      <p className='text-white/50 text-sm mb-4'>
        Your personal comments across the platform. Total: {total}
      </p>
      <Table
        columns={columns}
        dataSource={comments}
        rowKey='id'
        loading={loading}
        pagination={{
          total,
          current: page,
          pageSize: 20,
          onChange: (p) => setPage(p),
        }}
        locale={{ emptyText: <Empty description='No comments yet.' /> }}
        scroll={{ x: 700 }}
      />
    </div>
  )
}
