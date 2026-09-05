import { ReactNode } from 'react'

export interface ModelSlot {
  icon: ReactNode
  title: string
  desc: string
  status: 'active' | 'planned'
  color: string
}

// NOTE: icon entries are ReactNode placeholders — actual icons are assigned in consumer components
// This data-only definition avoids coupling to @ant-design/icons in the constants layer.
