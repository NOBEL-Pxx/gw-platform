import { Key, useEffect } from 'react'
import { usePagination } from 'ahooks'
import { Table, TableProps, Empty } from 'antd'
import { getErrorReports } from '@/service'
import { ErrorReportItem } from '@/types/api'

interface ErrorListPanelProps {
  selectedErrorId: string
  onSelect: (errorId: string) => void
}

const errorReportColumns: TableProps<ErrorReportItem>['columns'] = [
  { title: 'Anomaly Type', dataIndex: 'anomaly_type', width: 200 },
  { title: 'Band', dataIndex: 'band', width: 200 },
  {
    title: 'Decfield',
    dataIndex: 'decfield',
    width: 200,
    render: (value: number[] | undefined) => {
      if (!value || value.length === 0) return '-'
      if (value.length === 1) return `[${value[0]}]`
      const min = Math.min(...value)
      const max = Math.max(...value)
      return `[${min}, ${max}]`
    },
  },
  {
    title: 'RA Field',
    dataIndex: 'rafield',
    width: 200,
    render: (value: number[] | undefined) => {
      if (!value || value.length === 0) return '-'
      if (value.length === 1) return `[${value[0]}]`
      const min = Math.min(...value)
      const max = Math.max(...value)
      return `[${min}, ${max}]`
    },
  },
  { title: 'End Date', dataIndex: 'end_date', width: 200 },
  { title: 'FOV', dataIndex: 'fov', width: 200 },
  { title: 'Width', dataIndex: 'width', width: 200 },
  { title: 'Height', dataIndex: 'height', width: 200 },
  { title: 'Start Date', dataIndex: 'start_date', width: 200 },
  { title: 'Telescope', dataIndex: 'telescope', width: 200 },
]

export default function ErrorListPanel({
  selectedErrorId,
  onSelect,
}: ErrorListPanelProps) {
  const {
    data: errorReportsData,
    loading,
    pagination: paginationConfig,
  } = usePagination(
    async ({ current, pageSize }) => {
      const response = await getErrorReports({
        page: current,
        page_size: pageSize,
      })
      return {
        list: response?.data?.list || [],
        total: response?.data?.total_info?.total_count || 0,
      }
    },
    { defaultPageSize: 10 },
  )

  const errorReportsList = errorReportsData?.list || []
  const total = errorReportsData?.total || 0

  useEffect(() => {
    if (!loading && errorReportsList.length > 0) {
      const isSelectedInList = selectedErrorId
        ? errorReportsList.some((item) => item.error_id === selectedErrorId)
        : false
      if (!isSelectedInList) {
        onSelect(errorReportsList[0].error_id)
      }
    } else if (!loading && errorReportsList.length === 0 && selectedErrorId) {
      onSelect('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, errorReportsList])

  const handleRowChange = (selectedKeys: Key[]) => {
    const errorId = selectedKeys[0] as string
    if (errorId) {
      onSelect(errorId)
    }
  }

  return (
    <div
      className='w-full h-full'
      style={{ background: 'rgba(255,255,255,0.02)' }}
    >
      <h2 className='text-xl font-bold p-4 text-white/85'>Error List</h2>
      {errorReportsList.length > 0 ? (
        <div className='p-2'>
          <Table
            dataSource={errorReportsList}
            columns={errorReportColumns}
            rowSelection={{
              type: 'radio',
              onChange: handleRowChange,
              selectedRowKeys: selectedErrorId ? [selectedErrorId] : [],
            }}
            rowKey='error_id'
            scroll={{ x: 'max-content' }}
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
        <Empty description='No error reports found' />
      )}
    </div>
  )
}
