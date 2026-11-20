package main

import (
	"context"
	"flag"
	"fmt"
	"time"

	"github.com/zeromicro/go-zero/core/logx"
	"github.com/zeromicro/go-zero/rest"

	"mhagent/internal/config"
	"mhagent/internal/handler"
	"mhagent/internal/jobs"
	"mhagent/internal/svc"
)

func main() {
	confPath := flag.String("f", "etc/mhagent.yaml", "配置文件路径")
	flag.Parse()

	cfg, secrets, err := config.Load(*confPath)
	if err != nil {
		logx.Errorf("加载配置失败: %v", err)
		return
	}
	sc, err := svc.New(cfg, secrets, svc.Options{})
	if err != nil {
		logx.Errorf("初始化服务失败: %v", err)
		return
	}
	defer sc.Close()

	server := rest.MustNewServer(cfg.RestConf)
	defer server.Stop()
	handler.RegisterRoutes(server, sc)

	// 悬挂 hold 回收:超过 HoldReclaimMinutes 仍未结算的冻结额自动释放。
	jobs.StartHoldReclaimer(context.Background(), sc.DB, sc.Ledger, sc.Audit,
		time.Duration(cfg.Credits.HoldReclaimMinutes)*time.Minute, 5*time.Minute)

	fmt.Printf("mhagent 启动于 %s:%d (env=%s)\n", cfg.Host, cfg.Port, cfg.Env)
	server.Start()
}
