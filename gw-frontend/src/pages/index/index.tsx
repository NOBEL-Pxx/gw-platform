// R6.99-A: useBreakpoint drives Splitter vs stacked-Tabs layout.
// xs/sm/md (<992px): user sees one panel at a time via internal Tabs
//   (ErrorList | ErrorDetail | MultiBand) so panels don't get crushed.
// lg+ (>=992px): 3-column Splitter, original behavior.
import { useState } from 'react'
import { Grid, Splitter, Tabs } from 'antd'
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

  // R6.99-A: antd breakpoint hook. Returns {xs, sm, md, lg, xl, xxl}.
  const bp = Grid.useBreakpoint()
  const isCompact = !(bp.lg ?? false)
  const [mobileTab, setMobileTab] = useState<string>('abnormal')
  const TAB_BODY = {
    height: isCompact ? 'auto' : 'calc(100vh - 170px)',
    minHeight: 360,
  }

  // R6.99-A: shared body for the Abnormal Data tab.
  // Compact: ErrorList + ErrorDetail + MultiBand as inner Tabs (single
  //   panel visible at a time; user taps header to switch).
  // Wide: original 3-column Splitter.
  const abnormalBody = isCompact ? (
    <div style={{ ...TAB_BODY, padding: 8 }}>
      <Tabs
        activeKey={mobileTab}
        onChange={setMobileTab}
        items={[
          {
            key: 'list',
            label: 'Error Reports',
            children: (
              <ErrorListPanel
                selectedErrorId={selectedErrorId}
                onSelect={(id) => {
                  handleSelectError(id)
                  setMobileTab('detail')
                }}
              />
            ),
          },
          {
            key: 'detail',
            label: 'Detail',
            children: (
              <ErrorDetailPanel
                key={selectedErrorId}
                errorId={selectedErrorId}
                onSelectDetail={(uuid, ra, dec) => {
                  handleSelectDetail(uuid, ra, dec)
                  setMobileTab('multiband')
                }}
              />
            ),
          },
          {
            key: 'multiband',
            label: 'Multi-band',
            children: (
              <MultiBandDataPanel
                key={selectedUuid || selectedErrorId || 'empty'}
                ra={selectedRa}
                dec={selectedDec}
                uuid={selectedUuid}
              />
            ),
          },
        ]}
      />
    </div>
  ) : (
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
  )

  return (
    <div className='w-full h-full pt-3'>
      <Tabs
        defaultActiveKey='abnormal'
        tabBarStyle={{ paddingInlineStart: 24, paddingInlineEnd: 24 }}
        items={[
          {
            key: 'abnormal',
            label: 'Abnormal Data',
            children: abnormalBody,
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
