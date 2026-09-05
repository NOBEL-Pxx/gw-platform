import { useState } from 'react'
import { Button, Modal } from 'antd'
import CommentOutlined from '@ant-design/icons/CommentOutlined'
import Comments from './Comments'

function CommentsTrigger({ graveId }: { graveId: string }) {
  const [showComments, setShowComments] = useState(false)
  return (
    <>
      <Button
        type='primary'
        shape='circle'
        icon={<CommentOutlined />}
        onClick={() => setShowComments(!showComments)}
      />
      {showComments && (
        <Modal
          title='Comments'
          footer={null}
          onCancel={() => setShowComments(false)}
          open={showComments}
          width={800}
        >
          <Comments graveId={graveId} />
        </Modal>
      )}
    </>
  )
}

export default CommentsTrigger
