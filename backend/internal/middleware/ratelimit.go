package middleware

import (
	"fmt"
	"net/http"
	"time"

	"github.com/redis/go-redis/v9"

	"mhagent/internal/apierr"
)

// RateLimit 按用户固定窗口限流(Redis)。
func RateLimit(rdb *redis.Client, perMinute int, now func() time.Time) func(http.HandlerFunc) http.HandlerFunc {
	if perMinute <= 0 {
		perMinute = 30
	}
	if now == nil {
		now = time.Now
	}
	return func(next http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			userID, ok := apierr.UserID(r.Context())
			if !ok {
				next(w, r)
				return
			}
			bucket := now().UTC().Truncate(time.Minute).Unix()
			key := fmt.Sprintf("rl:%d:%d", userID, bucket)
			n, err := rdb.Incr(r.Context(), key).Result()
			if err != nil {
				apierr.WriteError(w, apierr.Internal())
				return
			}
			if n == 1 {
				_ = rdb.Expire(r.Context(), key, 2*time.Minute).Err()
			}
			if int(n) > perMinute {
				apierr.WriteError(w, apierr.RateLimited("请求过于频繁,请稍后重试"))
				return
			}
			next(w, r)
		}
	}
}
