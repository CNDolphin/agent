import type { ReactNode } from 'react'

interface PageHeaderProps {
  /** 模块编号，如 M-03，用于标识这是台账中的哪一页 */
  code: string
  title: string
  /** 标题右侧的标识，如单位或范围 */
  tag?: ReactNode
  description?: ReactNode
  actions?: ReactNode
}

export function PageHeader({ code, title, tag, description, actions }: PageHeaderProps) {
  return (
    <header className="page-head">
      <div>
        <div className="page-kicker">
          <span className="page-code">{code}</span>
          <span className="page-dash" aria-hidden="true" />
          {tag}
        </div>
        <h1 className="page-title">{title}</h1>
        {description ? <p className="page-desc">{description}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  )
}
