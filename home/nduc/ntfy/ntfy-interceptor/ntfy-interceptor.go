package main

import (
	"context"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"path"
	"strconv"
	"strings"
	"sync"
	"time"
)

var (
	maxFailedAttempts = 10
	resetInterval     = 1 * time.Minute
	maxTrackedUsers   = 1000 // Giới hạn số lượng user lưu trong map
)

// Cấu trúc lưu trữ số lần sai và thời gian sai cuối cùng của từng user
type attemptRecord struct {
	count      int
	lastUpdate time.Time
}

type contextKey string

const usernameKey contextKey = "username"

var (
	failedAttempts = make(map[string]attemptRecord)
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

	if usersStr := os.Getenv("MAX_TRACKED_USERS"); usersStr != "" {
		if val, err := strconv.Atoi(usersStr); err == nil && val > 0 {
			maxTrackedUsers = val
			log.Printf("Đã load cấu hình MAX_TRACKED_USERS = %d", maxTrackedUsers)
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

// Lấy IP thật từ Header do Cloudflare truyền về
func getRealIP(r *http.Request) string {
	// 1. Ưu tiên cao nhất: Header độc quyền của Cloudflare
	if ip := r.Header.Get("CF-Connecting-IP"); ip != "" {
		return ip
	}

	// 2. Fallback: Header tiêu chuẩn của các hệ thống Proxy
	if ip := r.Header.Get("X-Forwarded-For"); ip != "" {
		// X-Forwarded-For có thể chứa nhiều IP cách nhau bởi dấu phẩy (Client, Proxy1, Proxy2)
		// IP đầu tiên luôn là IP của Client
		ips := strings.Split(ip, ",")
		return strings.TrimSpace(ips[0])
	}

	// 3. Fallback cuối cùng: Trả về IP mạng nội bộ (thường sẽ là 127.0.0.1 nếu dùng cloudflared)
	return r.RemoteAddr
}

func main() {
	// Chặn và đợi cho đến khi ntfy thật (7899) mở port. Thử lại mỗi 5 giây.
	waitForBackend("127.0.0.1:7899", 5*time.Second)

	// Goroutine dọn dẹp (Garbage Collector)
	// Quét map theo định kỳ (bằng một nửa thời gian reset) để xóa các user đã hết hạn
	go func() {
		cleanInterval := resetInterval / 2
		if cleanInterval < 1*time.Second {
			cleanInterval = 1 * time.Second
		}
		ticker := time.NewTicker(cleanInterval)
		for range ticker.C {
			mu.Lock()
			now := time.Now()
			for user, record := range failedAttempts {
				// Nếu đã qua `resetInterval` kể từ lần sai cuối cùng -> xóa khỏi map
				if now.Sub(record.lastUpdate) > resetInterval {
					delete(failedAttempts, user)
				}
			}
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
			// Chuẩn hóa path để tránh bypass //v1/account/token/
			cleanedPath := path.Clean(req.URL.Path)

			if cleanedPath == "/v1/account/token" {
				if username, ok := req.Context().Value(usernameKey).(string); ok {
					mu.Lock()
					record := failedAttempts[username]

					// Nếu user có trong map nhưng đã quá thời gian reset -> đếm lại từ đầu
					if time.Since(record.lastUpdate) > resetInterval {
						record.count = 0
					}

					record.count++
					record.lastUpdate = time.Now()
					failedAttempts[username] = record

					log.Printf("[Cảnh báo] Sai mật khẩu tài khoản '%s' - Số lần thử: %d/%d (IP: %s)",
						username, record.count, maxFailedAttempts, getRealIP(req))
					mu.Unlock()
				}
			}
		}
		return nil
	}

	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		// Chuẩn hóa path trước khi kiểm tra
		cleanedPath := path.Clean(r.URL.Path)

		if cleanedPath == "/v1/account/token" {
			username, _, ok := r.BasicAuth()
			if ok {
				mu.Lock()
				record, userTracked := failedAttempts[username]

				// Dọn dẹp lười (Lazy cleanup) ngay lúc truy cập nếu user đó đã hết hạn
				if userTracked && time.Since(record.lastUpdate) > resetInterval {
					delete(failedAttempts, username)
					userTracked = false
					record = attemptRecord{}
				}

				totalTracked := len(failedAttempts)

				// Chỉ chặn nếu map đã đầy VÀ user này chưa hề có trong map (user mới)
				if !userTracked && totalTracked >= maxTrackedUsers {
					mu.Unlock()
					log.Printf("[BLOCK - Global] Chặn request từ IP %s do bộ nhớ đã đạt tối đa %d users theo dõi", getRealIP(r), maxTrackedUsers)
					w.WriteHeader(http.StatusTooManyRequests)
					return
				}

				count := record.count
				mu.Unlock()

				if count >= maxFailedAttempts {
					log.Printf("[BLOCK - User] Chặn đăng nhập vào tài khoản '%s' từ IP %s do sai mật khẩu quá %d lần", username, getRealIP(r), maxFailedAttempts)
					w.WriteHeader(http.StatusTooManyRequests)
					return
				}

				// Lưu username vào context để dùng cho hàm ModifyResponse
				ctx := context.WithValue(r.Context(), usernameKey, username)
				r = r.WithContext(ctx)
			}
		}

		proxy.ServeHTTP(w, r)
	})

	log.Printf("Bắt đầu chạy Interceptor tại cổng :7900 -> Forward đến :7899")
	log.Printf("Cấu hình hiện tại: Block sau %d lần sai, Giới hạn %d users trong map, Reset sau %v", maxFailedAttempts, maxTrackedUsers, resetInterval)

	server := &http.Server{
		Addr:              ":7900",
		ReadHeaderTimeout: 5 * time.Second,
		// Không nên set ReadTimeout, WriteTimeout quá ngắn nếu dùng WebSockets
	}

	if err := server.ListenAndServe(); err != nil {
		log.Fatalf("Lỗi khởi chạy server: %v", err)
	}
}