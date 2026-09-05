# 如何保持 Aladin 组件不重新挂载

## 问题描述

在使用 Aladin Lite 等需要初始化的第三方库时，如果组件因为条件渲染而重新挂载，会导致：

- 底图重新初始化（耗时较长）
- 用户体验差（闪烁、加载慢）
- 性能问题

## 问题场景

### ❌ 错误示例：条件渲染导致重新挂载

```tsx
function MyComponent({ ra, dec }) {
  return (
    <div>
      {ra !== undefined && dec !== undefined ? (
        <Aladin fits={fits} /> // ❌ 条件渲染会导致组件重新挂载
      ) : (
        <Empty />
      )}
    </div>
  )
}
```

**问题分析：**

- 当 `ra`/`dec` 从 `undefined` 变为有值时，`Aladin` 从不存在变为存在
- React 会重新创建组件实例，导致重新挂载
- 即使使用 `key` 属性，也无法避免条件渲染导致的重新挂载

## 解决方案

### ✅ 正确做法：始终挂载组件

```tsx
function MyComponent({ ra, dec }) {
  const fits = useMemo(() => {
    // 计算 fits 数组
    return ra !== undefined && dec !== undefined ? actualFits : []
  }, [ra, dec, actualFits])

  return (
    <div>
      {/* ✅ Aladin 始终挂载，只更新 props */}
      <Aladin key='aladin-viewer' fits={fits} />

      {ra !== undefined && dec !== undefined ? <OtherContent /> : <Empty />}
    </div>
  )
}
```

**关键点：**

1. **组件始终挂载**：将需要保持状态的组件移出条件渲染
2. **通过 props 控制显示**：当数据不可用时，传入空数组或默认值
3. **使用稳定的 key**：确保组件实例不会因为其他原因重新创建

## 完整示例

### 实际应用场景

```tsx
import { memo, useMemo, useState } from 'react'
import { useRequest } from 'ahooks'
import Aladin from './Aladin1'

interface MultiBandDataPanelProps {
  ra?: number
  dec?: number
}

function MultiBandDataPanel({ ra, dec }: MultiBandDataPanelProps) {
  const { data } = useRequest(
    () => getGravitationalWave({ ra: ra!, dec: dec! }),
    {
      ready: ra !== undefined && dec !== undefined,
      refreshDeps: [ra, dec],
    },
  )

  const list = useMemo(() => data?.data?.list || [], [data?.data?.list])
  const [selectedIndexes, setSelectedIndexes] = useState<number[]>([0])

  // 生成 fits 地址数组
  const fits = useMemo(
    () =>
      ra !== undefined && dec !== undefined
        ? selectedIndexes
            .map((idx) => list[idx]?.fits_db_path)
            .filter(Boolean)
            .map((path) => `http://example.com/fits/${path}`)
        : [], // ✅ 数据不可用时传入空数组
    [selectedIndexes, list, ra, dec],
  )

  return (
    <div>
      <h2>Multi-band Observation Data</h2>

      {/* ✅ Aladin 始终挂载，不会因为条件渲染而重新挂载 */}
      <div className='h-[calc(100%-240px)]'>
        <Aladin
          key='aladin-viewer' // ✅ 稳定的 key
          fits={fits} // ✅ 通过 props 控制，而不是条件渲染
        />
      </div>

      {/* 其他内容可以使用条件渲染 */}
      {ra !== undefined && dec !== undefined ? (
        <ThumbnailList list={list} />
      ) : (
        <Empty description='Select data to view' />
      )}
    </div>
  )
}

// ✅ 使用 React.memo 优化，避免不必要的重新渲染
export default memo(MultiBandDataPanel, (prevProps, nextProps) => {
  return prevProps.ra === nextProps.ra && prevProps.dec === nextProps.dec
})
```

## 关键原则

### 1. 需要保持状态的组件应该始终挂载

- ❌ 不要使用条件渲染来控制组件的存在/不存在
- ✅ 使用 props 来控制组件的行为和显示内容

### 2. 使用稳定的 key

```tsx
// ✅ 使用固定的字符串 key
<Aladin key='aladin-viewer' fits={fits} />

// ❌ 不要使用动态的 key（除非真的需要重新挂载）
<Aladin key={someDynamicValue} fits={fits} />
```

### 3. 通过 props 传递空值而不是条件渲染

```tsx
// ✅ 始终挂载，传入空数组
;<Aladin fits={hasData ? actualFits : []} />

// ❌ 条件渲染会导致重新挂载
{
  hasData ? <Aladin fits={actualFits} /> : null
}
```

## 其他优化技巧

### 1. 使用 React.memo 避免不必要的重新渲染

```tsx
export default memo(MyComponent, (prevProps, nextProps) => {
  // 只有当关键 props 改变时才重新渲染
  return prevProps.ra === nextProps.ra && prevProps.dec === nextProps.dec
})
```

### 2. 在组件内部使用 useRef 保存实例

```tsx
function Aladin({ fits }) {
  const aladinRef = useRef(null)

  useEffect(() => {
    // 只在首次挂载时初始化
    if (!aladinRef.current) {
      aladinRef.current = initializeAladin()
    }
  }, [])

  useEffect(() => {
    // 只更新图层，不重新初始化
    if (aladinRef.current) {
      updateLayers(aladinRef.current, fits)
    }
  }, [fits])
}
```

## 调试方法

### 检查组件是否重新挂载

在组件中添加日志：

```tsx
function Aladin({ fits }) {
  useEffect(() => {
    console.log('Aladin 初始化') // 如果多次出现，说明重新挂载了
    // 初始化逻辑
  }, [])

  useEffect(() => {
    console.log('FITS 更新', fits) // 这个可以多次出现，正常
    // 更新图层逻辑
  }, [fits])
}
```

### 使用 React DevTools

- 打开 React DevTools
- 查看组件树，观察组件是否被销毁和重新创建
- 如果组件在条件渲染中，会被标记为 "unmounted" 和 "mounted"

## 总结

**核心原则：**

1. **需要保持状态的组件始终挂载**
2. **通过 props 控制行为，而不是条件渲染控制存在**
3. **使用稳定的 key 和 React.memo 优化性能**

**常见错误：**

- ❌ 使用条件渲染控制需要保持状态的组件
- ❌ 使用动态 key 导致组件重新创建
- ❌ 在父组件重新渲染时没有使用 memo 优化

**正确做法：**

- ✅ 组件始终挂载，通过 props 传递数据
- ✅ 使用稳定的 key 和 React.memo
- ✅ 在组件内部使用 useRef 保存实例，避免重复初始化
