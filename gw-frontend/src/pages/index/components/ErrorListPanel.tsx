import { Key, useEffect } from 'react'
import { usePagination } from 'ahooks'
import { Table, TableProps, Empty } from 'antd'
import { getErrorReports } from '@/service'
import { ErrorReportItem } from '@/types/api'

interface ErrorListPanelProps {
  selectedErrorId: string
  onSelect: (errorId: string) => void
}

// R6.99-A: shrank 9-col table (1800px fixed) to 5-col + responsive.
// Decfield+RA Field merged into 'Sky Region'. FOV/Width/Height moved
// to a collapsible Details column on narrow viewports. Add `scroll`
// on <Table> to contain any horizontal overflow inside the panel
// (not the whole page).
const errorReportColumns: TableProps<ErrorReportItem>['columns'] = [
  {
    title: 'Anomaly Type',
    dataIndex: 'anomaly_type',
    width: 140,
    responsive: ['xs', 'sm', 'md', 'lg', 'xl', 'xxl'],
  },
  {
    title: 'Band',
    dataIndex: 'band',
    width: 90,
    responsive: ['xs', 'sm', 'md', 'lg', 'xl', 'xxl'],
  },
  {
    title: 'Sky Region',
    key: 'sky_region',
    width: 180,
    responsive: ['xs', 'sm', 'md', 'lg', 'xl', 'xxl'],
    render: (_, record) => {
      const ra = record.rafield
      const dec = record.decfield
      const fmt = (v: number[] | undefined) => {
        if (!v || v.length === 0) return '-'
        if (v.length === 1) return `${v[0]}`
        return `${Math.min(...v)}…${Math.max(...v)}`
      }
      return `RA ${fmt(ra)} / Dec ${fmt(dec)}`
    },
  },
  {
    title: 'Date',
    dataIndex: 'start_date',
    width: 110,
    responsive: ['sm', 'md', 'lg', 'xl', 'xxl'],
  },
  {
    title: 'Telescope',
    dataIndex: 'telescope',
    width: 110,
    responsive: ['md', 'lg', 'xl', 'xxl'],
  },
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
