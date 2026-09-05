import { Key, useEffect, useState } from 'react'
import { usePagination } from 'ahooks'
import { Empty, Table, TableProps, Typography } from 'antd'
import { getErrorReportDetail } from '@/service'
import type { ErrorDetailItem } from '@/types/api'
import CommentsTrigger from '@/pages/home/components/CommentsTrigger'
// v4.32: DL Anomaly Classifier removed
// import AnomalyClassifyPanel from "./AnomalyClassifyPanel"

const { Paragraph } = Typography

interface ErrorDetailPanelProps {
  errorId: string
  onSelectDetail: (uuid: string, ra: number, dec: number) => void
}

const errorDetailColumns: TableProps<ErrorDetailItem>['columns'] = [
  { title: 'RA', dataIndex: 'ra', width: 100 },
  { title: 'Dec', dataIndex: 'dec', width: 100 },
  { title: 'Anomaly Type', dataIndex: 'anomaly_type', width: 100 },
  {
    title: 'Comments',
    dataIndex: 'id',
    width: 120,
    render: (id) => <CommentsTrigger graveId={id} />,
  },
]

const LOG_BG = { background: 'rgba(255,255,255,0.03)' }
const LOG_BORDER = { border: '1px solid rgba(255,255,255,0.06)' }

export default function ErrorDetailPanel({
  errorId,
  onSelectDetail,
}: ErrorDetailPanelProps) {
  // v4.32: removed — was only used by DL Anomaly Classifier
  // const [selectedFitsPath, setSelectedFitsPath] = useState<string>("")
  // const [selectedRa, setSelectedRa] = useState<number>(0)
  // const [selectedDec, setSelectedDec] = useState<number>(0)
  const [selectedDetailUuid, setSelectedDetailUuid] = useState<string>('')
  const [logContent, setLogContent] = useState<string>('')

  const {
    data: errorDetailData,
    loading,
    pagination: paginationConfig,
  } = usePagination(
    async ({ current, pageSize }) => {
      if (!errorId) {
        return { list: [], total: 0, logContent: '' }
      }
      const response = await getErrorReportDetail(errorId, {
        page: current,
        page_size: pageSize,
      })
      const detailResponse = response?.data
      if (detailResponse?.logContent) {
        setLogContent(detailResponse.logContent)
      }
      return {
        list: detailResponse?.list || [],
        total: detailResponse?.total_info?.total_count || 0,
        logContent: detailResponse?.logContent || '',
      }
    },
    { defaultPageSize: 10, ready: !!errorId, refreshDeps: [errorId] },
  )

  const errorDetailsList = errorDetailData?.list || []
  const total = errorDetailData?.total || 0
  const displayLogContent = logContent || ''

  useEffect(() => {
    if (!loading && errorDetailsList.length > 0) {
      const isSelectedInList = selectedDetailUuid
        ? errorDetailsList.some((item) => item.uuid === selectedDetailUuid)
        : false
      if (!isSelectedInList) {
        const firstItem = errorDetailsList[0]
        setSelectedDetailUuid(firstItem.uuid)
        onSelectDetail(firstItem.uuid, firstItem.ra, firstItem.dec)
        // v4.32: removed (DL Anomaly Classifier)
      }
    } else if (
      !loading &&
      errorDetailsList.length === 0 &&
      selectedDetailUuid
    ) {
      setSelectedDetailUuid('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, errorDetailsList])

  useEffect(() => {
    setSelectedDetailUuid('')
  }, [errorId])

  const handleRowChange = (selectedKeys: Key[]) => {
    const uuid = selectedKeys[0] as string
    if (uuid) {
      const selectedItem = errorDetailsList.find((item) => item.uuid === uuid)
      if (selectedItem) {
        setSelectedDetailUuid(uuid)
        onSelectDetail(selectedItem.uuid, selectedItem.ra, selectedItem.dec)
        // v4.32: removed (DL Anomaly Classifier)
      }
    }
  }

  return (
    <div
      className='w-full h-full flex flex-col'
      style={{ background: 'rgba(255,255,255,0.02)' }}
    >
      <h2 className='text-xl font-bold p-4 text-white/85 flex-shrink-0'>
        Error Detail
      </h2>
      {/* min-h-0 is CRITICAL: overrides flex default min-height:auto so this shrinks below content size, enabling overflow scroll */}
      <div className='flex-1 min-h-0 overflow-y-scroll px-4 pb-4'>
        {displayLogContent && (
          <div
            className='pb-4 border-b'
            style={{ borderColor: 'rgba(255,255,255,0.06)' }}
          >
            <div className='flex items-center gap-2 mb-2'>
              <div className='text-sm font-semibold text-white/60'>
                Log Content:
              </div>
              <Paragraph
                copyable={{
                  text: displayLogContent,
                  tooltips: ['Copy', 'Copied'],
                }}
                style={{ margin: 0 }}
              />
            </div>
            <div
              className='rounded p-3 max-h-[200px] overflow-y-auto'
              style={{ ...LOG_BG, ...LOG_BORDER }}
            >
              <pre style={{ color: 'rgba(255,255,255,0.80)' }}>
                {displayLogContent}
              </pre>
            </div>
          </div>
        )}
        {/* v4.32: DL Anomaly Classifier removed — not currently needed */}

        {errorDetailsList.length > 0 ? (
          <div className='p-2'>
            <Table<ErrorDetailItem>
              dataSource={errorDetailsList}
              columns={errorDetailColumns}
              rowSelection={{
                type: 'radio',
                onChange: handleRowChange,
                selectedRowKeys: selectedDetailUuid ? [selectedDetailUuid] : [],
              }}
              rowKey='uuid'
              scroll={{ x: 400 }}
              loading={loading}
              pagination={{
                ...paginationConfig,
                total,
                showSizeChanger: true,
                showTotal: (totalCount) => `total: ${totalCount}`,
              }}
            />
          </div>
        ) : (
          <Empty description='Select an error report from the left list' />
        )}
      </div>
    </div>
  )
}
