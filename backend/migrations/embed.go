// Package migrations 内嵌数据库迁移脚本,供服务启动与测试执行。
package migrations

import _ "embed"

//go:embed 0001_init.up.sql
var InitUp string

//go:embed 0001_init.down.sql
var InitDown string

//go:embed 0002_users_password.up.sql
var AlterUp string

//go:embed 0003_deepseek_price.up.sql
var PriceUp string

//go:embed 0004_reports.up.sql
var ReportsUp string

//go:embed 0004_reports.down.sql
var ReportsDown string

//go:embed 0005_content_releases.up.sql
var ContentUp string

//go:embed 0005_content_releases.down.sql
var ContentDown string
