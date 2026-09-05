declare module 'firefly-api-access' {
  export interface FireflyAPI {
    showImage: (divId: string, params: Record<string, unknown>) => void
    util?: {
      image?: {
        RangeValues?: {
          serializeSimple: (
            stretch: string,
            lower: number,
            upper: number,
            scale: string,
          ) => string
        }
      }
      table?: {
        makeIrsaCatalogRequest: (...args: unknown[]) => Promise<unknown>
      }
      removeLayer?: (id: string) => void
      addActionListener?: (
        actionType: string,
        callback: (action: unknown, state: unknown) => void,
      ) => void
    }
    action?: Record<string, unknown>
  }
  export function initFirefly(serverUrl: string): () => Promise<FireflyAPI>
}
