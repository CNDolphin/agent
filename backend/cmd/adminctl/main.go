// cmd/adminctl 创建管理员账号,密码只从命令行或环境变量读取,不写入仓库。
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"strings"

	"golang.org/x/crypto/bcrypt"

	"mhagent/internal/model"
)

func main() {
	if len(os.Args) < 2 || os.Args[1] != "create" {
		fmt.Fprintln(os.Stderr, "用法: adminctl create -username <name> -role super|ops  (密码用 ADMIN_PASSWORD 环境变量传入)")
		os.Exit(2)
	}
	fs := flag.NewFlagSet("create", flag.ExitOnError)
	username := fs.String("username", "", "管理员用户名")
	role := fs.String("role", "ops", "角色: super | ops")
	password := fs.String("password", "", "密码;留空则读取 ADMIN_PASSWORD")
	_ = fs.Parse(os.Args[2:])

	if strings.TrimSpace(*username) == "" {
		fatal("username 不能为空")
	}
	if *role != "super" && *role != "ops" {
		fatal("role 只能是 super 或 ops")
	}
	pwd := *password
	if pwd == "" {
		pwd = os.Getenv("ADMIN_PASSWORD")
	}
	if pwd == "" {
		fatal("缺少密码:使用 -password 或 ADMIN_PASSWORD")
	}

	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		dsn = os.Getenv("ADMIN_DATABASE_URL")
	}
	if dsn == "" {
		fatal("缺少 DATABASE_URL")
	}
	db, err := model.Open(dsn, 4)
	if err != nil {
		fatal("连接数据库失败: " + err.Error())
	}
	defer db.Close()
	if err := model.EnsureUp(context.Background(), db); err != nil {
		fatal("初始化 schema 失败: " + err.Error())
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(pwd), bcrypt.DefaultCost)
	if err != nil {
		fatal("生成密码哈希失败")
	}

	var id int64
	err = db.QueryRowContext(context.Background(),
		`INSERT INTO admin_users (username, password_hash, role, created_at) VALUES ($1,$2,$3, now())
		 RETURNING id`, *username, string(hash), *role).Scan(&id)
	if err != nil {
		if isUniqueViolation(err) {
			fatal("用户名已存在")
		}
		fatal("创建管理员失败: " + err.Error())
	}
	fmt.Printf("管理员已创建: id=%d username=%s role=%s\n", id, *username, *role)
}

func isUniqueViolation(err error) bool {
	return strings.Contains(err.Error(), "duplicate key")
}

func fatal(msg string) {
	fmt.Fprintln(os.Stderr, msg)
	os.Exit(1)
}
