import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { downloadBlob, exportTimestamp } from '../export'

describe('export utility', () => {
  describe('downloadBlob', () => {
    let createObjectURLSpy: ReturnType<typeof vi.fn>
    let revokeObjectURLSpy: ReturnType<typeof vi.fn>
    let appendChildSpy: ReturnType<typeof vi.spyOn>
    let removeChildSpy: ReturnType<typeof vi.spyOn>
    let clickSpy: ReturnType<typeof vi.fn>

    beforeEach(() => {
      createObjectURLSpy = vi.fn(() => 'blob:mock-url')
      revokeObjectURLSpy = vi.fn()
      clickSpy = vi.fn()

      // Mock URL
      vi.stubGlobal('URL', {
        createObjectURL: createObjectURLSpy,
        revokeObjectURL: revokeObjectURLSpy,
      })

      // Mock document.createElement('a')
      const origCreate = document.createElement.bind(document)
      vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
        if (tag === 'a') {
          return {
            href: '',
            download: '',
            click: clickSpy,
          } as unknown as HTMLAnchorElement
        }
        return origCreate(tag)
      }) as typeof document.createElement)

      appendChildSpy = vi
        .spyOn(document.body, 'appendChild')
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .mockImplementation((() => {}) as any) as any
      removeChildSpy = vi
        .spyOn(document.body, 'removeChild')
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .mockImplementation((() => {}) as any) as any
    })

    afterEach(() => {
      vi.restoreAllMocks()
      vi.unstubAllGlobals()
    })

    it('calls URL.createObjectURL with the blob', () => {
      const blob = new Blob(['hello'])
      downloadBlob(blob, 'test.txt')
      expect(createObjectURLSpy).toHaveBeenCalledWith(blob)
    })

    it('calls anchor click() to trigger download', () => {
      downloadBlob(new Blob(['x']), 'foo.png')
      expect(clickSpy).toHaveBeenCalledTimes(1)
    })

    it('sets anchor download attribute to filename', () => {
      const origCreate = document.createElement.bind(document)
      vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
        if (tag === 'a') {
          return {
            href: '',
            download: '',
            click: clickSpy,
          } as unknown as HTMLAnchorElement
        }
        return origCreate(tag)
      }) as typeof document.createElement)

      let captured: HTMLAnchorElement | null = null
      ;(
        appendChildSpy as unknown as {
          mockImplementation: (fn: (node: Node) => Node) => unknown
        }
      ).mockImplementation((node: Node) => {
        captured = node as HTMLAnchorElement
        return node
      })

      downloadBlob(new Blob(['data']), 'my-export-2026.csv')
      expect(captured!.download).toBe('my-export-2026.csv')
    })

    it('appends anchor to body then removes it', () => {
      downloadBlob(new Blob(['x']), 'test')
      expect(appendChildSpy).toHaveBeenCalledTimes(1)
      expect(removeChildSpy).toHaveBeenCalledTimes(1)
    })

    it('revokes the object URL after click', () => {
      downloadBlob(new Blob(['x']), 'test')
      expect(revokeObjectURLSpy).toHaveBeenCalledWith('blob:mock-url')
    })
  })

  describe('exportTimestamp', () => {
    it('returns a string', () => {
      expect(typeof exportTimestamp()).toBe('string')
    })

    it('matches ISO 8601 format with - instead of : and .', () => {
      // Format: YYYY-MM-DDTHH-mm-ss (slice 0,19 of ISO with : and . replaced by -)
      const ts = exportTimestamp()
      expect(ts).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}$/)
    })

    it('produces same length string for any time', () => {
      expect(exportTimestamp().length).toBe(19)
    })

    it('produces valid date components', () => {
      const ts = exportTimestamp()
      // Parse back: replace first 2 hyphens back to colons (in time portion only)
      // ts = "2026-09-05T13-47-18" → "2026-09-05T13:47:18"
      const timePart = ts.split('T')[1]
      const [h, m, s] = timePart.split('-').map(Number)
      expect(h).toBeGreaterThanOrEqual(0)
      expect(h).toBeLessThan(24)
      expect(m).toBeGreaterThanOrEqual(0)
      expect(m).toBeLessThan(60)
      expect(s).toBeGreaterThanOrEqual(0)
      expect(s).toBeLessThan(60)
    })
  })
})
