import { Button, Card, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'

import { api } from '../api'
import type { CrisisInfo } from '../types'

const FALLBACK: CrisisInfo = {
  hotlines: [
    { name: '心理援助热线', number: '12356' },
    { name: '急救电话', number: '120' },
  ],
  message: '如果你现在有伤害自己的念头,请立即拨打 12356 或 120,或前往最近的急诊。',
  copy_text: '我现在状态很不好,需要你陪着我。如果联系不上我,请帮我拨打 12356 或 120。',
}

export function CrisisCard() {
  const [info, setInfo] = useState<CrisisInfo>(FALLBACK)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    api
      .get<CrisisInfo>('/crisis')
      .then((data) => setInfo(data))
      .catch(() => setInfo(FALLBACK))
  }, [])

  function copy() {
    navigator.clipboard
      ?.writeText(info.copy_text)
      .then(() => setCopied(true))
      .catch(() => setCopied(false))
  }

  return (
    <Card className="crisis-card" title="此刻的安全支持">
      <Typography.Paragraph strong>{info.message}</Typography.Paragraph>
      <Space wrap className="crisis-hotlines">
        {info.hotlines.map((item) => (
          <Tag key={item.number} color="red" className="hotline-tag">
            {item.name} {item.number}
          </Tag>
        ))}
      </Space>
      <Typography.Paragraph type="secondary" className="crisis-copy">
        {info.copy_text}
      </Typography.Paragraph>
      <Button onClick={copy}>{copied ? '已复制' : '复制求助文字'}</Button>
    </Card>
  )
}
