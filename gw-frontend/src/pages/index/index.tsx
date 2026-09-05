import { useState } from 'react'
import { Splitter, Tabs } from 'antd'
import ErrorListPanel from './components/ErrorListPanel'
import ErrorDetailPanel from './components/ErrorDetailPanel'
import MultiBandDataPanel from './components/MultiBandDataPanel'
import TODPage from '@/pages/tod'

function Index() {
  const [selectedErrorId, setSelectedErrorId] = useState<string>('')
  const [selectedRa, setSelectedRa] = useState<number | undefined>(undefined)
  const [selectedDec, setSelectedDec] = useState<number | undefined>(undefined)
  const [selectedUuid, setSelectedUuid] = useState<string | undefined>(
    undefined,
  )

  const handleSelectDetail = (uuid: string, ra: number, dec: number) => {
    setSelectedRa(ra)
    setSelectedDec(dec)
    setSelectedUuid(uuid)
  }

  // 当切换错误报告时，清空选中的详情
  const handleSelectError = (errorId: string) => {
    setSelectedErrorId(errorId)
    setSelectedRa(undefined)
    setSelectedDec(undefined)
    setSelectedUuid(undefined)
  }

  const TAB_BODY = { height: 'calc(100vh - 170px)' }

  return (
    <div className='w-full h-full pt-3'>
      <Tabs
        defaultActiveKey='abnormal'
        tabBarStyle={{ paddingInlineStart: 24, paddingInlineEnd: 24 }}
        items={[
          {
            key: 'abnormal',
            label: 'Abnormal Data',
            children: (
              <div style={TAB_BODY}>
                <Splitter className='w-full h-full'>
                  {/* 第一列：错误报告列表 */}
                  <Splitter.Panel defaultSize='33%' min='0' max='50%'>
                    <ErrorListPanel
                      selectedErrorId={selectedErrorId}
                      onSelect={handleSelectError}
                    />
                  </Splitter.Panel>

                  {/* 第二列：错误详情 */}
                  <Splitter.Panel defaultSize='33%' min='0' max='50%'>
                    <ErrorDetailPanel
                      key={selectedErrorId}
                      errorId={selectedErrorId}
                      onSelectDetail={handleSelectDetail}
                    />
                  </Splitter.Panel>

                  {/* 第三列：Multi-band Observation Data */}
                  <Splitter.Panel>
                    <MultiBandDataPanel
                      key={selectedUuid || selectedErrorId || 'empty'}
                      ra={selectedRa}
                      dec={selectedDec}
                      uuid={selectedUuid}
                    />
                  </Splitter.Panel>
                </Splitter>
              </div>
            ),
          },
          {
            key: 'tod',
            label: 'AliCPT TOD',
            children: (
              <div style={{ ...TAB_BODY, overflow: 'auto' }}>
                <TODPage />
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}

export default Index
