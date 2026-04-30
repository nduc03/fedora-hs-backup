package main

import (
	"context"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strconv"
	"sync"
	"time"
)

var (
	maxFailedAttempts = 10
	resetInterval     = 1 * time.Minute
)

type contextKey string

const usernameKey contextKey = "username"

var (
	failedAttempts = make(map[string]int)
	mu             sync.Mutex
)

func init() {
	if attemptsStr := os.Getenv("MAX_FAILED_ATTEMPTS"); attemptsStr != "" {
		if val, err := strconv.Atoi(attemptsStr); err == nil && val > 0 {
			maxFailedAttempts = val
			log.Printf("Đã load cấu hình MAX_FAILED_ATTEMPTS = %d", maxFailedAttempts)
		}
	}

	if intervalStr := os.Getenv("RESET_INTERVAL_MINUTES"); intervalStr != "" {
		if val, err := strconv.Atoi(intervalStr); err == nil && val > 0 {
			resetInterval = time.Duration(val) * time.Minute
			log.Printf("Đã load cấu hình RESET_INTERVAL_MINUTES = %d phút", val)
		}
	}
}

// Hàm kiểm tra kết nối tới backend
func waitForBackend(address string, retryInterval time.Duration) {
	log.Printf("Đang kiểm tra kết nối tới backend %s...", address)
	for {
		// Thử mở kết nối TCP tới cổng của ntfy thật với timeout 2 giây
		conn, err := net.DialTimeout("tcp", address, 2*time.Second)
		if err == nil {
			conn.Close()
			log.Printf("Đã kết nối thành công tới %s!", address)
			break
		}
		log.Printf("Backend %s chưa sẵn sàng (%v). Thử lại sau %v...", address, err, retryInterval)
		time.Sleep(retryInterval)
	}
}

func main() {
	// Chặn và đợi cho đến khi ntfy thật (7899) mở port. Thử lại mỗi 5 giây.
	waitForBackend("127.0.0.1:7899", 5*time.Second)

	// Sau khi backend đã sẵn sàng, khởi chạy goroutine để reset bộ đếm
	go func() {
		ticker := time.NewTicker(resetInterval)
		for range ticker.C {
			mu.Lock()
			failedAttempts = make(map[string]int)
			mu.Unlock()
		}
	}()

	targetURL, err := url.Parse("http://127.0.0.1:7899")
	if err != nil {
		log.Fatalf("Lỗi parse URL: %v", err)
	}

	proxy := httputil.NewSingleHostReverseProxy(targetURL)

	proxy.ModifyResponse = func(resp *http.Response) error {
		if resp.StatusCode == http.StatusUnauthorized {
			req := resp.Request
			if req.URL.Path == "/v1/account/token" {
				if username, ok := req.Context().Value(usernameKey).(string); ok {
					mu.Lock()
					failedAttempts[username]++
					log.Printf("[Cảnh báo] Sai mật khẩu tài khoản '%s' - Số lần thử: %d/%d", username, failedAttempts[username], maxFailedAttempts)
					mu.Unlock()
				}
			}
		}
		return nil
	}

	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/account/token" {
			username, _, ok := r.BasicAuth()
			if ok {
				mu.Lock()
				count := failedAttempts[username]
				mu.Unlock()

				if count >= maxFailedAttempts {
					w.WriteHeader(http.StatusTooManyRequests)
					return
				}

				ctx := context.WithValue(r.Context(), usernameKey, username)
				r = r.WithContext(ctx)
			}
		}

		proxy.ServeHTTP(w, r)
	})

	log.Printf("Bắt đầu chạy Interceptor tại cổng :7900 -> Forward đến :7899")
	log.Printf("Cấu hình hiện tại: Block sau %d lần sai, Reset sau %v", maxFailedAttempts, resetInterval)

	if err := http.ListenAndServe(":7900", nil); err != nil {
		log.Fatalf("Lỗi khởi chạy server: %v", err)
	}
}