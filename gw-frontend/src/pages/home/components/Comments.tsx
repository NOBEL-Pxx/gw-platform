import { useState, useEffect } from 'react'
import { getComments, postComment, exportCommentsCsv } from '@/service'
import { useRequest } from 'ahooks'
import {
  List,
  Avatar,
  Input,
  Button,
  Form,
  Spin,
  Empty,
  Pagination,
  Select,
  Tooltip,
} from 'antd'
import UserOutlined from '@ant-design/icons/UserOutlined'
import SendOutlined from '@ant-design/icons/SendOutlined'
import DownloadOutlined from '@ant-design/icons/DownloadOutlined'
import { Link } from 'react-router-dom'
import { message } from '@/util/AntdMessage'
import { CommentItem } from '@/types/api'
import { useAuth } from '@/contexts/AuthContext'

const { TextArea } = Input
const DEFAULT_PAGE_SIZE = 10
function Comments({ graveId }: { graveId: string }) {
  const { user } = useAuth()
  const [comments, setComments] = useState<CommentItem[]>([])
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [exporting, setExporting] = useState(false)

  const {
    data,
    loading,
    run: runQueryComments,
  } = useRequest(getComments, {
    refreshDeps: [graveId],
    manual: true,
    onSuccess: (data) => {
      if (data?.data?.list) {
        setComments(data.data.list)
      }
    },
  })
  const totalInfo = data?.data?.total_info
  const total = totalInfo?.total_count || 0
  const page = totalInfo?.page || 1
  const pageSize = totalInfo?.page_size || 10

  // v4.13: Export comments as CSV
  const handleExport = async () => {
    setExporting(true)
    try {
      const csvText = await exportCommentsCsv({ grawaveId: graveId })
      const blob = new Blob([csvText], { type: 'text/csv;charset=UTF-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `comments_${graveId}_${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
      message.success('Comments exported')
    } catch {
      message.error('Export failed')
    } finally {
      setExporting(false)
    }
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (!values.content || values.content.trim() === '') {
        return
      }

      setSubmitting(true)

      try {
        await postComment({
          content: values.content,
          grawaveId: graveId,
          userId: user?.userId || 'anonymous',
          category: values.category,
        })

        runQueryComments(graveId, {
          page: 1,
          page_size: DEFAULT_PAGE_SIZE,
        })

        form.resetFields()
      } catch (error) {
        console.error('Comment submission failed:', error)
        message.error('Failed to post comment. Please try again.')
      } finally {
        setSubmitting(false)
      }
    } catch (error) {
      console.error('Form validation failed:', error)
    }
  }

  useEffect(() => {
    if (graveId) {
      runQueryComments(graveId, { page: 1, page_size: DEFAULT_PAGE_SIZE })
    }
  }, [graveId, runQueryComments])

  return (
    <div className='comments-container'>
      {/* v4.13: Export button */}
      {comments.length > 0 && (
        <div className='flex justify-end mb-2'>
          <Tooltip title='Download comments as CSV'>
            <Button
              size='small'
              icon={<DownloadOutlined />}
              loading={exporting}
              onClick={handleExport}
            >
              Export CSV
            </Button>
          </Tooltip>
        </div>
      )}

      {/* Comment list */}
      {loading ? (
        <div className='flex flex-center my-4'>
          <Spin />
        </div>
      ) : comments.length > 0 ? (
        <>
          <List
            itemLayout='horizontal'
            dataSource={comments}
            renderItem={(item) => (
              <List.Item>
                <List.Item.Meta
                  avatar={<Avatar icon={<UserOutlined />} />}
                  title={<span>{item.username || item.userId}</span>}
                  description={`[${item.category}]: ${item.content}`}
                />
                <div>{item.createdAt}</div>
              </List.Item>
            )}
          />
          <div className='flex justify-center mt-4'>
            <Pagination
              total={total}
              onChange={(page, pageSize) => {
                runQueryComments(graveId, { page, page_size: pageSize })
              }}
              pageSize={pageSize}
              current={page}
            />
          </div>
        </>
      ) : (
        <Empty description='No comments yet' />
      )}

      {/* Comment form */}
      <div className='mt-4 pt-4 border-t'>
        {!user && (
          <div className='text-center py-4 text-white/50 font-medium'>
            <Link
              to='/login'
              className='!text-aurora-cyan hover:!text-aurora-cyan/80 font-semibold'
            >
              Login
            </Link>{' '}
            to leave a comment
          </div>
        )}
        <Form
          form={form}
          initialValues={{ category: 'false_alarm' }}
          disabled={!user}
        >
          <Form.Item
            name='category'
            label='Comment Category'
            className='font-semibold'
          >
            <Select
              options={[
                { label: 'False Alarm', value: 'false_alarm' },
                { label: 'Data Error', value: 'data_error' },
                { label: 'Other', value: 'other' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name='content'
            rules={[
              { required: true, message: 'Please enter comment content' },
            ]}
          >
            <TextArea
              rows={4}
              placeholder='Write a comment...'
              maxLength={500}
              showCount
            />
          </Form.Item>
          <Form.Item className='mb-0 text-right'>
            <Button
              type='primary'
              icon={<SendOutlined />}
              loading={submitting}
              onClick={handleSubmit}
              disabled={!user}
            >
              {user ? 'Submit' : 'Login to Comment'}
            </Button>
          </Form.Item>
        </Form>
      </div>
    </div>
  )
}

export default Comments
