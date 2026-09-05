import { Form, Button, InputNumber } from 'antd'
import type { FormProps } from 'antd'
import { useSearchParams } from 'react-router-dom'

type FieldType = {
  ra?: number
  dec?: number
  radius?: number
}

function Search() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initFormParams = Object.fromEntries(searchParams.entries())
  const handleSearch: FormProps<FieldType>['onFinish'] = (values) => {
    // 过滤掉为空的情况
    const params = Object.entries(values).reduce((acc, [key, value]) => {
      if (value && key in values) {
        const fieldKey = key as keyof FieldType
        acc[fieldKey] = value
      }
      return acc
    }, {} as FieldType)
    const urlParams = new URLSearchParams(
      Object.entries(params).map(([key, value]) => [key, String(value)]),
    )
    setSearchParams(urlParams)
  }
  return (
    <div>
      <Form
        layout='inline'
        onFinish={handleSearch}
        initialValues={initFormParams}
      >
        <Form.Item label='RA' name='ra'>
          <InputNumber placeholder='0~360' min={0} max={360} />
        </Form.Item>
        <Form.Item label='DEC' name='dec'>
          <InputNumber placeholder='-90~90' min={-90} max={90} />
        </Form.Item>
        <Form.Item label='Search Radius' name='radius'>
          <InputNumber placeholder='>0 deg' min={0} step={1} />
        </Form.Item>
        <Form.Item>
          <Button type='primary' htmlType='submit'>
            Search
          </Button>
        </Form.Item>
      </Form>
    </div>
  )
}

export default Search
