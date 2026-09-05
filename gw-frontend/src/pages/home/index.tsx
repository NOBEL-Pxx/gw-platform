import { useEffect, useMemo, useState, Key, useCallback } from 'react'
import { useRequest } from 'ahooks'
import { useSearchParams } from 'react-router-dom'
import {
  Table,
  TableProps,
  Empty,
  Splitter,
  Button,
  Tooltip,
  message as antMsg,
} from 'antd'
import HeartOutlined from '@ant-design/icons/HeartOutlined'
import HeartFilled from '@ant-design/icons/HeartFilled'

import Search from './components/Search'
import { getGravitationalWave, toggleFavorite, checkFavorites } from '@/service'
import { GravitationalWaveItem } from '@/types/api'
import ImageList from './components/ImageList'
import CommentsTrigger from './components/CommentsTrigger'
import { useAuth } from '@/contexts/AuthContext'

function Index() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [selectedId, setSelectedId] = useState<Key>('')
  const { user } = useAuth()
  const [favoritedMap, setFavoritedMap] = useState<Record<string, boolean>>({})

  const gravitationalWaveParams = useMemo(
    () => Object.fromEntries(searchParams.entries()),
    [searchParams],
  )
  const { data, loading, run } = useRequest(
    (opts) => getGravitationalWave(opts),
    {
      manual: true,
      onSuccess: (res) => {
        const list = res?.data?.list
        if (list?.length > 0) {
          const surveyItem = list.find(
            (item: GravitationalWaveItem) => (item.width || 0) > 100,
          )
          const curItem = surveyItem || list[0]
          setSelectedId(curItem.id)
          // Check favorite statuses
          if (user && list.length > 0) {
            checkFavorites(list.map((it: GravitationalWaveItem) => it.id))
              .then((res) => {
                if (res.data)
                  setFavoritedMap((prev) => ({ ...prev, ...res.data }))
              })
              .catch(() => {})
          }
        }
      },
    },
  )
  const list = data?.data?.list
  const totalInfo = data?.data?.total_info

  const handleToggleFavorite = useCallback(
    async (item: GravitationalWaveItem) => {
      if (!user) {
        antMsg.warning('Login to save favorites')
        return
      }
      try {
        const res = await toggleFavorite({
          grawaveId: item.id,
          band: item.band,
          ra: item.ra,
          dec: item.dec,
          telescope: item.telescope,
        })
        const action = res.data?.action
        setFavoritedMap((prev) => ({
          ...prev,
          [item.id]: action === 'added',
        }))
        antMsg.success(
          action === 'added' ? 'Added to favorites' : 'Removed from favorites',
        )
      } catch {
        /* handled */
      }
    },
    [user],
  )

  const columns: TableProps<GravitationalWaveItem>['columns'] = [
    {
      title: '',
      dataIndex: 'id',
      width: 44,
      key: 'fav',
      render: (id: string, record: GravitationalWaveItem) => (
        <Tooltip
          title={
            favoritedMap[id] ? 'Remove from favorites' : 'Add to favorites'
          }
        >
          <Button
            type='text'
            size='small'
            onClick={(e) => {
              e.stopPropagation()
              handleToggleFavorite(record)
            }}
            icon={
              favoritedMap[id] ? (
                <HeartFilled style={{ color: '#FF006E' }} />
              ) : (
                <HeartOutlined style={{ color: 'rgba(255,255,255,0.4)' }} />
              )
            }
          />
        </Tooltip>
      ),
    },
    { title: 'Band', dataIndex: 'band', width: 100 },
    { title: 'RA', dataIndex: 'ra', width: 100 },
    { title: 'Dec', dataIndex: 'dec', width: 100 },
    {
      title: 'Start Date',
      dataIndex: 'start_date',
      width: 100,
      render: (v: number) => v || '-',
    },
    {
      title: 'End Date',
      dataIndex: 'end_date',
      width: 100,
      render: (v: number) => v || '-',
    },
    { title: 'Telescope', dataIndex: 'telescope', width: 120 },
    {
      title: 'Comments',
      dataIndex: 'id',
      width: 100,
      render: (id: string) => <CommentsTrigger graveId={id} />,
    },
  ]

  const handlePaginationChange = (page: number, page_size: number) => {
    setSearchParams({
      ...gravitationalWaveParams,
      page: page.toString(),
      page_size: page_size.toString(),
    })
  }

  const handleRowChange = (selectedKeys: Key[]) => {
    const id = selectedKeys[0]
    setSelectedId(id)
  }
  const selectedItem = list?.find(
    (item: GravitationalWaveItem) => item.id === selectedId,
  )

  useEffect(() => {
    run({ page: 1, page_size: 10, ...gravitationalWaveParams })
  }, [gravitationalWaveParams, run])

  return (
    <Splitter className='w-full h-full'>
      <Splitter.Panel defaultSize='50%' min='0' max='50%'>
        <div className='w-full h-full'>
          <div className='p-2'>
            <Search />
          </div>
          {list && list.length > 0 ? (
            <div className='p-2'>
              <Table
                dataSource={list}
                columns={columns}
                rowSelection={{
                  type: 'radio',
                  onChange: handleRowChange,
                  selectedRowKeys: [selectedId],
                }}
                rowKey={'id'}
                loading={loading}
                scroll={{ x: 700 }}
                pagination={{
                  pageSize: totalInfo?.page_size,
                  total: totalInfo?.total_count,
                  showSizeChanger: true,
                  onChange: handlePaginationChange,
                  showTotal: () => {
                    const tc = totalInfo?.total_count || 0
                    const ps = totalInfo?.page_size || 10
                    return tc <= ps
                      ? `${tc} results (all shown)`
                      : `total: ${tc}`
                  },
                }}
              />
            </div>
          ) : (
            <Empty description='Click Search or enter RA/Dec/Radius to query observations' />
          )}
        </div>
      </Splitter.Panel>
      <Splitter.Panel>
        <div
          className='w-full h-full flex flex-col overflow-y-auto'
          style={{ background: 'rgba(255,255,255,0.02)' }}
        >
          <div className='flex items-center justify-between p-4'>
            <h2 className='text-xl font-bold text-white/85'>
              Multi-band Observation Data
            </h2>
            {selectedItem && user && (
              <Tooltip
                title={
                  favoritedMap[selectedItem.id as string]
                    ? 'Remove from favorites'
                    : 'Add to favorites'
                }
              >
                <Button
                  type={
                    favoritedMap[selectedItem.id as string]
                      ? 'primary'
                      : 'default'
                  }
                  size='small'
                  danger={favoritedMap[selectedItem.id as string]}
                  icon={
                    favoritedMap[selectedItem.id as string] ? (
                      <HeartFilled />
                    ) : (
                      <HeartOutlined />
                    )
                  }
                  onClick={() =>
                    selectedItem && handleToggleFavorite(selectedItem)
                  }
                >
                  {favoritedMap[selectedItem.id as string]
                    ? 'Favorited'
                    : 'Favorite'}
                </Button>
              </Tooltip>
            )}
          </div>
          {selectedItem ? (
            <ImageList ra={selectedItem.ra} dec={selectedItem.dec} />
          ) : (
            <Empty description='Select a row from the table' />
          )}
        </div>
      </Splitter.Panel>
    </Splitter>
  )
}

export default Index
