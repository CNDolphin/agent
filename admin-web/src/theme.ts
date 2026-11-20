import type { ThemeConfig } from 'antd'

/**
 * 「神经基因组检验台账」主题：
 * 检验纸冷灰底 + 墨蓝字 + 螺旋青主色，数字统一等宽对齐，像一份可审计的检验单。
 */
export const adminTheme: ThemeConfig = {
  token: {
    colorPrimary: '#0C8F86',
    colorInfo: '#2C4CC4',
    colorLink: '#2C4CC4',
    colorSuccess: '#1F8A5B',
    colorWarning: '#B4761F',
    colorError: '#B23A48',
    colorBgLayout: '#F2F6F7',
    colorBgContainer: '#FFFFFF',
    colorBgElevated: '#FFFFFF',
    colorBorder: '#D8E3E7',
    colorBorderSecondary: '#E7EEF1',
    colorText: '#0E1B23',
    colorTextSecondary: '#4A5F6B',
    colorTextTertiary: '#7C8F99',
    borderRadius: 6,
    borderRadiusLG: 10,
    controlHeight: 34,
    fontSize: 14,
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'PingFang SC', 'HarmonyOS Sans SC', 'Microsoft YaHei', 'Segoe UI', sans-serif",
  },
  components: {
    Layout: {
      headerBg: 'rgba(255,255,255,0.82)',
      headerHeight: 64,
      siderBg: '#0B1720',
      bodyBg: 'transparent',
    },
    Menu: {
      darkItemBg: 'transparent',
      darkSubMenuItemBg: 'transparent',
      darkItemColor: '#8FA6B2',
      darkItemHoverColor: '#DCEDEA',
      darkItemSelectedBg: 'rgba(12,143,134,0.16)',
      darkItemSelectedColor: '#EAF7F4',
      itemHeight: 42,
      itemMarginInline: 10,
      itemBorderRadius: 6,
    },
    Table: {
      headerBg: '#F5F9FA',
      headerColor: '#4A5F6B',
      headerSplitColor: 'transparent',
      rowHoverBg: '#F0F7F7',
      borderColor: '#E7EEF1',
      cellPaddingBlock: 12,
      footerBg: '#F5F9FA',
    },
    Card: {
      headerBg: 'transparent',
    },
    Statistic: {
      contentFontSize: 28,
      titleFontSize: 12,
    },
    Button: {
      fontWeight: 500,
      primaryShadow: 'none',
      defaultShadow: 'none',
    },
    Tag: {
      defaultBg: '#F1F6F7',
      defaultColor: '#4A5F6B',
    },
    Drawer: {
      footerPaddingBlock: 12,
    },
  },
}
