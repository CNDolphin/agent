// Package sse 提供进程内的服务端事件推送中心。
package sse

import (
	"sync"

	"github.com/zeromicro/go-zero/core/logx"
)

// Event 是一条待推送的事件。
type Event struct {
	ID   string
	Type string
	Data []byte
}

// Hub 按用户维护订阅者集合。单实例内存实现,不做跨进程广播。
type Hub struct {
	mu   sync.Mutex
	subs map[int64]map[chan Event]struct{}
}

// NewHub 创建空 Hub。
func NewHub() *Hub {
	return &Hub{subs: make(map[int64]map[chan Event]struct{})}
}

// Subscribe 订阅指定用户的事件,返回事件通道与取消函数(幂等)。
func (h *Hub) Subscribe(userID int64) (<-chan Event, func()) {
	ch := make(chan Event, 8)
	h.mu.Lock()
	if h.subs[userID] == nil {
		h.subs[userID] = make(map[chan Event]struct{})
	}
	h.subs[userID][ch] = struct{}{}
	h.mu.Unlock()

	var once sync.Once
	cancel := func() {
		once.Do(func() {
			h.mu.Lock()
			if set, ok := h.subs[userID]; ok {
				delete(set, ch)
				if len(set) == 0 {
					delete(h.subs, userID)
				}
			}
			h.mu.Unlock()
			close(ch)
		})
	}
	return ch, cancel
}

// Publish 向用户的所有订阅者非阻塞推送;缓冲满时丢弃并记日志。
func (h *Hub) Publish(userID int64, ev Event) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for ch := range h.subs[userID] {
		select {
		case ch <- ev:
		default:
			logx.Errorf("sse: 订阅者缓冲已满,丢弃事件 user=%d type=%s", userID, ev.Type)
		}
	}
}

// Broadcast 向所有在线订阅者推送全局事件(如内容更新),不区分用户。
func (h *Hub) Broadcast(ev Event) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for userID, chs := range h.subs {
		for ch := range chs {
			select {
			case ch <- ev:
			default:
				logx.Errorf("sse: 订阅者缓冲已满,丢弃广播事件 user=%d type=%s", userID, ev.Type)
			}
		}
	}
}
