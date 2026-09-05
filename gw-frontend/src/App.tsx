import { RouterProvider } from 'react-router-dom'
import {
  StyleProvider,
  // legacyLogicalPropertiesTransformer,
} from '@ant-design/cssinjs'
import router from './router'

function App() {
  return (
    <StyleProvider
    // hashPriority='high'
    // transformers={[legacyLogicalPropertiesTransformer]}
    >
      <RouterProvider router={router}></RouterProvider>
    </StyleProvider>
  )
}

export default App
