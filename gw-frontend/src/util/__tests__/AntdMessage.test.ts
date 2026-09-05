import { describe, it, expect, vi } from 'vitest'

// Mock antd App.useApp to return our stub instances.
const messageMock = {
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
  loading: vi.fn(),
  open: vi.fn(),
  destroy: vi.fn(),
}
const notificationMock = {
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
  open: vi.fn(),
  destroy: vi.fn(),
}
const modalMock = {
  confirm: vi.fn(),
  info: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  destroy: vi.fn(),
}

vi.mock('antd', () => ({
  App: {
    useApp: () => ({
      message: messageMock,
      notification: notificationMock,
      modal: modalMock,
    }),
  },
}))

// Import AFTER vi.mock so the mock is wired up.
import AntdMessage from '../AntdMessage'
import * as AntdMessageModule from '../AntdMessage'

describe('AntdMessage utility', () => {
  it('exports a default function component', () => {
    expect(AntdMessage).toBeDefined()
    expect(typeof AntdMessage).toBe('function')
  })

  it('exports named bindings for message, notification, modal', () => {
    expect('message' in AntdMessageModule).toBe(true)
    expect('notification' in AntdMessageModule).toBe(true)
    expect('modal' in AntdMessageModule).toBe(true)
  })

  it('default export is callable and returns null (React component shape)', () => {
    const result = (AntdMessage as unknown as () => null)()
    expect(result).toBeNull()
  })

  it('after component runs once, named exports are populated with mock instances', () => {
    ;(AntdMessage as unknown as () => null)()
    expect(AntdMessageModule.message).toBe(messageMock)
    expect(AntdMessageModule.notification).toBe(notificationMock)
    expect(AntdMessageModule.modal).toBe(modalMock)
  })

  it('modal excludes warn (intentional per module comment)', () => {
    ;(AntdMessage as unknown as () => null)()
    expect(
      (AntdMessageModule.modal as unknown as { warn?: unknown }).warn,
    ).toBeUndefined()
  })

  it('message has standard Ant Design message methods', () => {
    ;(AntdMessage as unknown as () => null)()
    const msg = AntdMessageModule.message as unknown as Record<string, unknown>
    expect(typeof msg.success).toBe('function')
    expect(typeof msg.error).toBe('function')
    expect(typeof msg.warning).toBe('function')
    expect(typeof msg.info).toBe('function')
  })

  it('notification has standard Ant Design notification methods', () => {
    ;(AntdMessage as unknown as () => null)()
    const n = AntdMessageModule.notification as unknown as Record<
      string,
      unknown
    >
    expect(typeof n.success).toBe('function')
    expect(typeof n.error).toBe('function')
    expect(typeof n.open).toBe('function')
  })

  it('modal has standard Ant Design modal methods', () => {
    ;(AntdMessage as unknown as () => null)()
    const m = AntdMessageModule.modal as unknown as Record<string, unknown>
    expect(typeof m.confirm).toBe('function')
    expect(typeof m.info).toBe('function')
    expect(typeof m.success).toBe('function')
    expect(typeof m.error).toBe('function')
  })
})
